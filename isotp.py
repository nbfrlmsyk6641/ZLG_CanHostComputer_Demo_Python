# isotp.py
import time
from zlgcan import * 

# ISO-TP 帧类型定义，主要处理4种帧类型
ISOTP_FRAME_SF = 0x00 # 单帧
ISOTP_FRAME_FF = 0x10 # 首帧
ISOTP_FRAME_CF = 0x20 # 连续帧
ISOTP_FRAME_FC = 0x30 # 流控帧

# 网络层定时参数
ISOTP_TIMEOUT_N_BS = 2.0
ISOTP_TIMEOUT_N_CR = 2.0

# ISO-TP 协议实现类
class IsoTpLayer:
    def __init__(self, zcan_lib, chn_handle, tx_id, rx_id):
        """
        初始化 ISO-TP 层
        :param zcan_lib: zcan 对象实例 (ZCAN())
        :param chn_handle: CAN 通道句柄
        :param tx_id: 发送 ID (上位机 -> MCU, 如 0x7E0)
        :param rx_id: 接收 ID (MCU -> 上位机, 如 0x7E8)
        """
        self.zcan = zcan_lib
        self.chn = chn_handle
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.timeout_n_bs = ISOTP_TIMEOUT_N_BS

    def _send_raw_frame(self, data_bytes):
        """发送一帧原始 CAN 报文 (8字节)"""
        # ISO-TP 规定不足 8 字节补 0x00
        pad_len = 8 - len(data_bytes)
        if pad_len > 0:
            data_bytes += [0x00] * pad_len

        # 构造 ZLG 发送结构体 
        msg = ZCAN_Transmit_Data()
        msg.transmit_type = 0 # 正常发送
        msg.frame.eff = 0     # 标准帧 (0)
        msg.frame.rtr = 0     # 数据帧
        msg.frame.can_id = self.tx_id
        msg.frame.can_dlc = 8
        
        for i in range(8):
            msg.frame.data[i] = data_bytes[i]

        ret = self.zcan.Transmit(self.chn, msg, 1)
        return ret == 1

    def _wait_flow_control(self):
        """等待 MCU 回复流控帧 (FC)"""
        start_time = time.time()

        while time.time() - start_time < self.timeout_n_bs:
            # 查询缓冲区 
            num = self.zcan.GetReceiveNum(self.chn, ZCAN_TYPE_CAN)
            if num > 0:
                # 读取报文 
                msgs, cnt = self.zcan.Receive(self.chn, num)
                for i in range(cnt):
                    msg = msgs[i].frame
                    # 判断 ID 是否匹配且是 FC 帧 (0x30)
                    if msg.can_id == self.rx_id and (msg.data[0] & 0xF0) == ISOTP_FRAME_FC:
                        # 解析 FC 参数
                        fs = msg.data[0] & 0x0F # FlowStatus (0=CTS, 1=WT, 2=OVFLW)
                        bs = msg.data[1]        # BlockSize
                        st_min = msg.data[2]    # SeparationTime
                        return True, fs, bs, st_min
            
            time.sleep(0.002) # 避免 CPU 满载

        print(f"[ISO-TP Error] N_Bs Timeout! (MCU 未在 {self.timeout_n_bs}s 内回复 FC)")    
        return False, 0, 0, 0

    def send(self, data):
        """
        ISO-TP 发送入口函数
        :param data: 要发送的完整数据 (list 或 bytes)
        :return: True 成功, False 失败
        """
        # 统一转为 list
        if isinstance(data, bytes):
            data = list(data)
            
        length = len(data)
        
        # ---------------------------------------------------------
        # 情况 A: 数据短，用单帧 (SF)
        # ---------------------------------------------------------
        if length <= 7:
            # 构造 SF: [PCI(0)|Len] + Data
            frame_data = [ISOTP_FRAME_SF | length] + data
            print(f"[ISO-TP] 发送单帧 (Len={length})")
            return self._send_raw_frame(frame_data)

        # ---------------------------------------------------------
        # 情况 B: 数据长，用多帧 (FF + FC + CF...)
        # ---------------------------------------------------------
        else:
            print(f"[ISO-TP] 发送多帧 (Len={length})")
            
            # 1. 发送首帧 (FF)
            # --------------------------------
            # Byte0: PCI(1)|Len_High, Byte1: Len_Low
            len_high = (length >> 8) & 0x0F
            len_low  = length & 0xFF
            
            # FF 包含前 6 个字节的数据
            frame_data = [ISOTP_FRAME_FF | len_high, len_low] + data[0:6]
            
            if not self._send_raw_frame(frame_data):
                print("[Error] 首帧发送失败")
                return False
                
            # 2. 等待流控帧 (FC)
            # --------------------------------
            ok, fs, bs, st_min = self._wait_flow_control()
            
            if not ok:
                print("[Error] 等待流控帧超时 (MCU没反应)")
                return False
            
            if fs != 0: # 如果不是 CTS (Continue To Send)
                print(f"[Error] MCU 拒绝接收 (FS={fs})")
                return False
                
            # 解析 STmin (简单处理 0-127ms)
            delay_s = 0
            if st_min <= 0x7F:
                delay_s = st_min / 1000.0 # 毫秒转秒
            elif 0xF1 <= st_min <= 0xF9:
                delay_s = (st_min - 0xF0) * 0.0001 # 100微秒转秒
            
            block_size = bs
            
            print(f"[ISO-TP] 收到流控: BS={bs}, STmin={st_min} (延时 {delay_s:.4f}s)")


            # 3. 发送连续帧 (CF)
            # --------------------------------
            offset = 6 # 已经发了6个
            sn = 1     # 序列号从1开始
            frame_count_in_block = 0
            
            while offset < length:
                # 截取最多 7 个字节
                chunk = data[offset : offset + 7]
                
                # 构造 CF: [PCI(2)|SN] + Data
                frame_data = [ISOTP_FRAME_CF | sn] + chunk
                
                if not self._send_raw_frame(frame_data):
                    return False
                
                # 变量更新
                offset += len(chunk)
                sn = (sn + 1) & 0x0F # 0-15 循环
                frame_count_in_block += 1

                if block_size > 0 and frame_count_in_block >= block_size:
                    print(f"[ISO-TP] 已发送 {frame_count_in_block} 帧，等待中间流控...")

                    ok, fs, new_bs, new_st = self._wait_flow_control()
                    if not ok: return False
                    if fs != 0: return False

                    block_size = new_bs
                    delay_s = self._calc_st_min(new_st)
                    frame_count_in_block = 0

                    continue
                
                # 执行 MCU 要求的延时 (关键!)
                if delay_s > 0:
                    time.sleep(delay_s)
            
            print("[ISO-TP] 传输完成")
            return True
    
    def _calc_st_min(self, st_min_val):
        """辅助函数：解析 STmin"""
        if st_min_val <= 0x7F:
            return st_min_val / 1000.0 # ms
        elif 0xF1 <= st_min_val <= 0xF9:
            return (st_min_val - 0xF0) * 0.0001 # 100us
        return 0.1 # 默认安全值