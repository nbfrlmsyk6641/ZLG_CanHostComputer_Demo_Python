# uds_flasher_final.py
import time
import struct
import binascii
import os
from zlgcan import * 
from isotp import IsoTpLayer 

# ==============================================================================
# 1. 全局配置 
# ==============================================================================
DEVICE_TYPE = ZCAN_USBCAN1
DEVICE_INDEX = 0
CHANNEL_INDEX = 0

# CAN ID (物理寻址)
TX_ID = 0x7E0 
RX_ID = 0x7E8

FIRMWARE_FILE = "Application.bin"

# 块大小配置
# MCU 定义缓冲区为 4096 (ISOTP_MAX_BUF_SIZE)
# 减去 2 字节协议头 (SID + BlockSeq) = 4094
# 为了 Flash 写入对齐 (4字节)，我们使用 4092
MAX_BLOCK_SIZE = 4092 

# ==============================================================================
# 2. UDS 客户端封装
# ==============================================================================
class UdsClient:
    def __init__(self, isotp_layer):
        self.tp = isotp_layer

    def request(self, req_data, desc="", timeout=3.0):
        """
        发送 UDS 请求并等待肯定响应
        :param req_data: 请求数据列表 [SID, Param1...]
        :param timeout: 等待超时时间 (秒)
        """
        sid = req_data[0]
        print(f"\n[UDS] >>> 请求 {desc} ({hex(sid)}) Data: {[hex(x) for x in req_data[1:]]}")
        
        # 1. 发送 (ISO-TP 层自动处理分包)
        if not self.tp.send(req_data):
            print(f"[Error] 发送失败")
            return False, []

        # 2. 等待响应 (轮询 ISO-TP 接收)
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # 这里直接操作 zcan 接收，实际项目中建议封装在 isotp.recv()
            num = self.tp.zcan.GetReceiveNum(self.tp.chn, ZCAN_TYPE_CAN)
            if num > 0:
                msgs, cnt = self.tp.zcan.Receive(self.tp.chn, num)
                for i in range(cnt):
                    msg = msgs[i].frame
                    # 简单过滤 ID
                    if msg.can_id == self.tp.rx_id:
                        # 简单解析 ISO-TP 单帧 (SF)
                        # (MCU 的响应通常很短，几乎都是 SF，这里简化处理)
                        # 严谨做法应该完善 isotp.py 的接收重组逻辑
                        if (msg.data[0] & 0xF0) == 0x00:
                            length = msg.data[0] & 0x0F
                            resp = list(msg.data[1 : 1+length])
                            
                            # A. 肯定响应 (SID + 0x40)
                            if resp[0] == (sid + 0x40):
                                print(f"[UDS] <<< 肯定响应: {[hex(x) for x in resp]}")
                                return True, resp
                                
                            # B. 否定响应 (0x7F)
                            elif resp[0] == 0x7F:
                                # 特殊处理 Pending (0x78) - 忙等待
                                if resp[2] == 0x78:
                                    print("[UDS] ... MCU 正在处理 (Pending) ...")
                                    start_time = time.time() # 重置超时，继续等
                                else:
                                    print(f"[Error] 否定响应 NRC: 0x{resp[2]:02X}")
                                    # 如果有附加数据 (例如 CRC 错误时的调试值)，打印出来
                                    if len(resp) > 3:
                                        print(f"      附加调试数据: {[hex(x) for x in resp[3:]]}")
                                    return False, resp
            
            time.sleep(0.005) # 释放 CPU
        
        print(f"[Error] 等待响应超时 ({timeout}s)")
        return False, []

# ==============================================================================
# 3. 主流程 (严格匹配 MCU 状态机)
# ==============================================================================
def main_flash_process():
    # --- A. 初始化硬件 ---
    zcan = ZCAN()
    handle = zcan.OpenDevice(DEVICE_TYPE, DEVICE_INDEX, 0)
    if handle == INVALID_DEVICE_HANDLE:
        print("打开设备失败")
        return

    print("--- CAN 初始化 ---")
    zcan.ZCAN_SetValue(handle, "0/canfd_abit_baud_rate", "1000000")
    chn_cfg = ZCAN_CHANNEL_INIT_CONFIG()
    chn_cfg.can_type = ZCAN_TYPE_CAN
    chn_cfg.config.can.mode = 0
    chn_handle = zcan.InitCAN(handle, CHANNEL_INDEX, chn_cfg)
    zcan.StartCAN(chn_handle)

    # --- B. 初始化协议栈 ---
    tp = IsoTpLayer(zcan, chn_handle, TX_ID, RX_ID)
    uds = UdsClient(tp)

    try:
        # =================================================================
        # 阶段 1: App 跳转 (App Logic)
        # 逻辑依据: App_main.txt 
        # 必须顺序: 10 03 -> 31 01 -> 10 02
        # =================================================================
        print("\n=== 阶段 1: App 跳转 Bootloader ===")
        
        # 1.1 进入扩展会话
        ok, _ = uds.request([0x10, 0x03], "App: Enter Extended Session")
        # 注意: 如果已经是在 Bootloader，这里可能会失败或回复不同，但我们假设是从 App 开始
        if not ok:
            print(">>> 提示: 可能是 MCU 已经在 Bootloader，尝试直接继续...")
        
        time.sleep(0.1)

        # 1.2 预编程检查
        ok, _ = uds.request([0x31, 0x01, 0xFF, 0x00], "App: Pre-Prog Check")
        # 如果这里失败，说明没进扩展会话或者 ID 不对，必须终止
        
        time.sleep(0.1)

        # 1.3 请求编程会话 (触发复位)
        ok, _ = uds.request([0x10, 0x02], "App: Enter Prog Session (Jump)")
        if ok:
            print(">>> MCU 正在复位，等待 2 秒让 Bootloader 启动...")
            time.sleep(2.0) 
        else:
            print(">>> 跳转请求失败 (或已在 Bootloader)")

        # =================================================================
        # 阶段 2: 固件下载 (Bootloader Logic)
        # 逻辑依据: Boot_main.txt
        # 必须顺序: 10 02 -> 34 -> 31 -> 36(Loop) -> 37
        # =================================================================
        print("\n=== 阶段 2: 固件下载 ===")

        # --- 准备固件数据 ---
        print(f"读取文件: {FIRMWARE_FILE}")
        with open(FIRMWARE_FILE, 'rb') as f:
            fw_data = f.read()
        
        # 4字节填充 (为了配合 MCU 的 32位 CRC 校验和 Flash 写入)
        if len(fw_data) % 4 != 0:
            fw_data += b'\xFF' * (4 - (len(fw_data) % 4))
        
        total_len = len(fw_data)
        # 计算 CRC (标准 PKZIP 算法, 对应 MCU V7 软件算法)
        total_crc = binascii.crc32(fw_data) & 0xFFFFFFFF
        
        print(f"固件大小: {total_len} Bytes")
        print(f"固件 CRC: 0x{total_crc:08X}")

        # 2.1 握手 (确认 Bootloader 在线)
        ok, _ = uds.request([0x10, 0x02], "Boot: Handshake (10 02)")
        if not ok: raise Exception("无法连接到 Bootloader")

        # 2.2 请求下载 (34)
        # 格式: 34 [Size 4B] [CRC 4B] (小端)
        req_34 = [0x34] + list(struct.pack('<I', total_len)) + list(struct.pack('<I', total_crc))
        ok, _ = uds.request(req_34, "Request Download (34)")
        if not ok: raise Exception("请求下载失败")

        # 2.3 擦除 Flash (31)
        # 格式: 31 01 FF 00
        # 超时: 给 10 秒，因为 MCU 会发 Pending，但我们要允许它慢
        ok, _ = uds.request([0x31, 0x01, 0xFF, 0x00], "Erase Flash (31)", timeout=10.0)
        if not ok: raise Exception("擦除失败")

        # 2.4 传输数据 (36 Loop)
        print("\n>>> 开始传输数据...")
        offset = 0
        block_seq = 1
        
        while offset < total_len:
            # 计算当前块大小
            size = min(MAX_BLOCK_SIZE, total_len - offset)
            block_data = fw_data[offset : offset + size]
            
            # 构造: 36 [Seq] [Data...]
            # 这里的 block_seq 需要 & 0xFF，虽然 Python 自动处理，但显式写更好
            req_36 = [0x36, block_seq & 0xFF] + list(block_data)
            
            print(f"Block {block_seq}: Offset={offset}, Len={size}")
            
            # 发送并等待响应 (76)
            # ISO-TP 层会自动拆包成 FF/CF 发送，并处理 MCU 的流控
            ok, _ = uds.request(req_36, f"Transfer Data")
            if not ok: raise Exception(f"Block {block_seq} 写入失败")
            
            # 稍微延时，给 MCU 一点喘息时间重置状态机 (虽然 STmin 已经控制了，但双重保险)
            time.sleep(0.05)
            
            offset += size
            block_seq += 1

        # 2.5 请求退出并校验 (37)
        print("\n>>> 传输完成，请求校验...")
        ok, _ = uds.request([0x37], "Request Exit (Verify CRC)")
        
        if ok:
            print("\n=== [SUCCESS] 刷写成功！MCU 正在重启... ===")
        else:
            # 如果 MCU 返回了附带 CRC 的否定响应，这里会打印出来
            raise Exception("CRC 校验失败")

    except Exception as e:
        print(f"\n[FATAL ERROR] 流程终止: {e}")
    
    finally:
        zcan.CloseDevice(handle)

if __name__ == "__main__":
    main_flash_process()