# iap_tool.py

import time
import os
import binascii
import struct # 导入struct库用于打包
from zlgcan import * # ==============================================================================
# --- 1. 协议常量定义 ---
# ==============================================================================

# --- 上位机 -> MCU 的CAN ID ---
HOST_REQUEST_ID_APP_RESET = 0xC0
HOST_REQUEST_ID_METADATA = 0xC1 
HOST_REQUEST_ID_DATA = 0xC2 
HOST_REQUEST_ID_EOT = 0xC3 

# --- MCU -> 上位机 的CAN ID ---
MCU_RESPONSE_ID_APP_ACK = 0xA0 
MCU_RESPONSE_ID_BL_READY = 0xB0 
MCU_RESPONSE_ID_ERASE_OK = 0xB1 
MCU_RESPONSE_ID_DATA_ACK = 0xB2 
MCU_RESPONSE_ID_VERIFY_OK = 0xB3 

# --- 协议中约定的特定数据 ---
APP_RESET_DATA = (c_ubyte * 8)(0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11)
BL_READY_DATA = (c_ubyte * 8)(0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22)
BL_ERASE_OK_DATA = (c_ubyte * 8)(0x33, 0x33, 0x33, 0x33, 0x33, 0x33, 0x33, 0x33)

DATA_PACKET_HD = 0xAA 
EOT_PACKET_ED = 0xBB 

# --- 工具配置 ---
DEVICE_TYPE = ZCAN_USBCAN1
DEVICE_INDEX = 0
CHANNEL_INDEX = 0

# --- 固件文件配置 ---
FIRMWARE_FILE_PATH = "Application.bin" 
APP_MAX_SIZE_BYTES = 300 * 1024 # App分区最大 300KB

# ==============================================================================
# --- 2. 辅助函数 ---
# ==============================================================================

def connect_can_bus(zcan, dev_handle):
    chn_cfg = ZCAN_CHANNEL_INIT_CONFIG()
    chn_cfg.can_type = ZCAN_TYPE_CAN
    ret = zcan.ZCAN_SetValue(dev_handle, "0/canfd_abit_baud_rate", "1000000")
    if ret != ZCAN_STATUS_OK:
        print(f"错误: 设置波特率(1Mbps)失败!")
        return INVALID_CHANNEL_HANDLE
    chn_cfg.config.can.mode = 0
    chn_handle = zcan.InitCAN(dev_handle, CHANNEL_INDEX, chn_cfg)
    if chn_handle == INVALID_CHANNEL_HANDLE:
        print(f"错误: 初始化CAN通道 {CHANNEL_INDEX} 失败!")
        return INVALID_CHANNEL_HANDLE
    ret = zcan.StartCAN(chn_handle)
    if ret != ZCAN_STATUS_OK:
        print(f"错误: 启动CAN通道 {CHANNEL_INDEX} 失败!")
        return INVALID_CHANNEL_HANDLE
    print(f"CAN通道 {CHANNEL_INDEX} 已启动 (1Mbps)")
    return chn_handle

def send_can_message(zcan, chn_handle, can_id, data, dlc):
    msg = ZCAN_Transmit_Data()
    msg.transmit_type = 0
    msg.frame.eff = 0
    msg.frame.rtr = 0
    msg.frame.can_id = can_id
    msg.frame.can_dlc = dlc
    for i in range(dlc):
        msg.frame.data[i] = data[i]
    ret = zcan.Transmit(chn_handle, msg, 1)
    if ret == 1:
        return True
    else:
        print(f" > 发送 ID: 0x{can_id:X} 失败!")
        return False

# ==============================================================================
# --- 3. IAP主逻辑 ---
# ==============================================================================

def main_iap_flow():
    zcan = ZCAN() 
    handle = zcan.OpenDevice(DEVICE_TYPE, DEVICE_INDEX, 0)
    if handle == INVALID_DEVICE_HANDLE:
        print("错误: 打开设备失败!")
        return

    print(f"设备已打开, 句柄: {handle}")

    chn_handle = connect_can_bus(zcan, handle)
    if chn_handle == INVALID_CHANNEL_HANDLE:
        zcan.CloseDevice(handle)
        return

    try:
        # --- 协议第1步：发送“重启”指令给App ---
        print(f"\n--- 步骤 1: 请求App重启进入Bootloader (发送 ID: 0x{HOST_REQUEST_ID_APP_RESET:X}) ---")
        if not send_can_message(zcan, chn_handle, HOST_REQUEST_ID_APP_RESET, APP_RESET_DATA, 8):
             raise Exception("发送重启指令失败")
        print(f" > 已发送“重启”指令 (ID: 0x{HOST_REQUEST_ID_APP_RESET:X})")


        # --- 协议第2步：等待Bootloader“就绪”响应 ---
        print(f"\n--- 步骤 2: 等待Bootloader就绪 (监听 ID: 0x{MCU_RESPONSE_ID_BL_READY:X}) ---")
        timeout = 5.0 # 5秒总超时
        start_time = time.time()
        bootloader_ready = False
        app_ack_received = False

        while time.time() - start_time < timeout:
            rcv_num = zcan.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)
            
            if rcv_num > 0:
                rcv_msgs, act_num = zcan.Receive(chn_handle, rcv_num if rcv_num < 10 else 10)
                
                for i in range(act_num):
                    msg = rcv_msgs[i].frame
                    print(f" < 收到报文 ID: 0x{msg.can_id:X}") 

                    if msg.can_id == MCU_RESPONSE_ID_APP_ACK and not app_ack_received:
                        print(" > 收到App确认(0xA0)，MCU正在重启...")
                        app_ack_received = True

                    if msg.can_id == MCU_RESPONSE_ID_BL_READY and msg.can_dlc == 8:
                        if all(msg.data[j] == BL_READY_DATA[j] for j in range(8)):
                            print("\n*** 成功！Bootloader已就绪 (收到 0xB0 + 0x22...)！ ***")
                            bootloader_ready = True
                            break 
                    
                    elif msg.can_id == 0xB0 and msg.data[0] == 0x00:
                         print("\n*** 警告：Bootloader已正常启动 (收到 0xB0 + 0x00...) ***")
                         print("   更新请求可能未收到。")
            
            if bootloader_ready:
                break 
            
            time.sleep(0.01) 

        if not bootloader_ready:
            print(f"\n*** 失败：等待Bootloader就绪响应(0x{MCU_RESPONSE_ID_BL_READY:X})超时 (5秒) ***")
            raise Exception("等待Bootloader就绪超时")
            
        
        # -----------------------------------------------------------------
        # --- 协议第3步：读取文件, 计算CRC, 并发送元数据 ---
        # -----------------------------------------------------------------
        print(f"\n--- 步骤 3: 发送固件元数据 (ID: 0x{HOST_REQUEST_ID_METADATA:X}) ---")
        
        try:
            print(f" > 正在读取文件: {FIRMWARE_FILE_PATH}")
            with open(FIRMWARE_FILE_PATH, 'rb') as f:
                firmware_data = f.read()
            total_size = len(firmware_data)
        except FileNotFoundError:
            raise Exception(f"固件文件 '{FIRMWARE_FILE_PATH}' 未找到!")

        print(f" > 文件大小: {total_size} 字节")
        if total_size == 0 or total_size > APP_MAX_SIZE_BYTES:
            raise Exception(f"固件大小无效 ({total_size} 字节). 必须大于0且小于 {APP_MAX_SIZE_BYTES} 字节.")

        crc_value = binascii.crc32(firmware_data) & 0xFFFFFFFF
        print(f" > 文件 CRC32: 0x{crc_value:08X}")

        # 打包元数据: 4字节大小(小端) + 4字节CRC(小端)
        payload_bytes = struct.pack('<II', total_size, crc_value)
            
        if not send_can_message(zcan, chn_handle, HOST_REQUEST_ID_METADATA, payload_bytes, 8):
             raise Exception("发送元数据报文失败!")
        
        print(f" > 已发送元数据。")

        # -----------------------------------------------------------------
        # --- 协议第4步：等待Bootloader“擦除完毕”响应 ---
        # -----------------------------------------------------------------
        print(f"\n--- 步骤 4: 等待Flash擦除完毕 (监听 ID: 0x{MCU_RESPONSE_ID_ERASE_OK:X}) ---")
        
        erase_timeout = 15.0 # Flash擦除慢，给15秒长超时
        start_time = time.time()
        erase_complete = False

        while time.time() - start_time < erase_timeout:
            rcv_num = zcan.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)
            
            if rcv_num > 0:
                rcv_msgs, act_num = zcan.Receive(chn_handle, rcv_num if rcv_num < 10 else 10)
                
                for i in range(act_num):
                    msg = rcv_msgs[i].frame
                    print(f" < 收到报文 ID: 0x{msg.can_id:X}") 

                    # 检查是否是“擦除完毕”报文
                    if msg.can_id == MCU_RESPONSE_ID_ERASE_OK and msg.can_dlc == 8:
                        if all(msg.data[j] == BL_ERASE_OK_DATA[j] for j in range(8)):
                            print("\n*** 成功！Bootloader已擦除Flash (收到 0xB1 + 0x33...)！ ***")
                            erase_complete = True
                            break 
            
            if erase_complete:
                break 
            
            time.sleep(0.01)

        if not erase_complete:
            print(f"\n*** 失败：等待擦除完毕响应(0x{MCU_RESPONSE_ID_ERASE_OK:X})超时 ({erase_timeout}秒) ***")
            raise Exception("擦除超时")

        # -----------------------------------------------------------------
        # --- 协议第5步：(暂存) ---
        # -----------------------------------------------------------------
        print("\n--- 成功进入下一阶段 ---")
        print("下一步：循环发送数据包")
        
        time.sleep(1) # 短暂暂停


    except Exception as e:
        print(f"\n--- IAP流程因错误而终止: {e} ---")
    finally:
        # --- 清理工作 ---
        print("\n正在关闭CAN通道和设备...")
        if chn_handle != INVALID_CHANNEL_HANDLE:
            zcan.ResetCAN(chn_handle)
        if handle != INVALID_DEVICE_HANDLE:
            zcan.CloseDevice(handle)
        print("清理完毕。")


# ==============================================================================
# --- 4. 启动入口 ---
# ==============================================================================

if __name__ == "__main__":
    print("===== IAP 固件更新工具 (命令行版 v0.3) =====")
    print("本脚本将执行IAP握手流程的第1-4步。")
    print("请确保：")
    print(" 1. CAN盒子已连接。")
    print(" 2. STM32开发板已烧录App和Bootloader程序。")
    print(f" 3. {FIRMWARE_FILE_PATH} 固件文件已放在本目录下。")
    print(" 4. App正在运行。")
    input(f"\n按回车键(Enter)开始发送“重启”指令 (ID: 0x{HOST_REQUEST_ID_APP_RESET:X})...")
    
    main_iap_flow()