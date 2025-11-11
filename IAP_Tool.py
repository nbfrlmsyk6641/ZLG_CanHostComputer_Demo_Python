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
MCU_RESPONSE_ID_ERROR = 0xB4 

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

# --- 协议参数 ---
PACKET_PAYLOAD_SIZE = 6 # 每包传输6字节固件
DATA_ACK_TIMEOUT_S = 0.5 # 等待数据包ACK的超时时间 (500ms)
VERIFY_TIMEOUT_S = 10.0 # 等待MCU校验固件的长超时时间 (10s)
MAX_RETRIES = 3 # 最大重传次数

# --- 2. 辅助函数 ---

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


# --- 3. IAP主逻辑 ---

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

    rcv_msgs = (ZCAN_Receive_Data * 10)() # 创建一个10帧的接收缓冲区
    ack_num = 0

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
                firmware_data = f.read() # firmware_data 是一个 bytes 对象
            
            # 1. 检查原始大小
            original_size = len(firmware_data)
            print(f" > 原始文件大小: {original_size} 字节")
            if original_size == 0 or original_size > APP_MAX_SIZE_BYTES:
                raise Exception(f"固件大小无效 ({original_size} 字节).")

            # 2. 对齐到4字节 (用 0xFF 填充)
            total_size = original_size # 先设为原始大小
            if total_size % 4 != 0:
                padding_needed = 4 - (total_size % 4)
                firmware_data += b'\xFF' * padding_needed # 在末尾添加 0xFF
                total_size = len(firmware_data) # 更新 total_size 为对齐后的大小
                print(f" > (已填充 {padding_needed} 字节 0xFF 以对齐到4字节)")
            
            print(f" > 最终发送大小: {total_size} 字节")

        except FileNotFoundError:
            raise Exception(f"固件文件 '{FIRMWARE_FILE_PATH}' 未找到!")
        
        crc_value = binascii.crc32(firmware_data) & 0xFFFFFFFF
        
        print(f" > 文件 CRC32 (基于 {total_size} 字节): 0x{crc_value:08X}")

        # 4. 打包 *填充后* 的大小和CRC
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
        # --- 协议第5、6、7步数据传输循环 ---
        # -----------------------------------------------------------------
        print(f"\n--- 步骤 5/6/7: 开始数据传输循环 ---")

        bytes_sent = 0
        sequence_num = 0

        while bytes_sent < total_size:
            # a. 准备数据块 (切片)，每次传6字节数据
            chunk = firmware_data[bytes_sent : bytes_sent + PACKET_PAYLOAD_SIZE]
            
            # b. 准备CAN报文 (8字节)
            payload = bytearray(8) # 创建一个8字节的可修改数组
            payload[0] = DATA_PACKET_HD # 0xAA
            payload[1] = sequence_num
            
            # c. 填充数据和 0xFF (处理最后一包)
            payload[2:2+len(chunk)] = chunk
            if len(chunk) < PACKET_PAYLOAD_SIZE:
                for i in range(len(chunk), PACKET_PAYLOAD_SIZE):
                    payload[2+i] = 0xFF
            
            # d. 发送与等待ACK (带重传)
            retry_count = 0
            ack_received = False
            
            while retry_count <= MAX_RETRIES and not ack_received:
                if retry_count > 0:
                    print(f" > (重传 {retry_count}/{MAX_RETRIES}) 正在发送数据包 {sequence_num}...")
                else:
                    # 打印进度
                    print(f" > 正在发送数据包 {sequence_num} ({bytes_sent + len(chunk)} / {total_size} 字节)...")

                if not send_can_message(zcan, chn_handle, HOST_REQUEST_ID_DATA, payload, 8):
                    raise Exception(f"发送数据包 {sequence_num} 失败!")
                
                # e. 启动短超时, 等待ACK
                wait_start_time = time.time()
                while time.time() - wait_start_time < DATA_ACK_TIMEOUT_S:
                    rcv_num = zcan.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)
                    if rcv_num > 0:
                        rcv_msgs, act_num = zcan.Receive(chn_handle, rcv_num if rcv_num < 10 else 10)
                        for i in range(act_num):
                            msg = rcv_msgs[i].frame
                            
                            # 检查是否是我们期待的ACK
                            if msg.can_id == MCU_RESPONSE_ID_DATA_ACK and msg.data[0] == sequence_num:
                                ack_received = True
                                break # 成功收到ACK
                    if ack_received:
                        break
                    time.sleep(0.005) # 5ms轮询
                
                if ack_received:
                    break # 成功，跳出重传循环
                
                # 如果执行到这里，说明超时了
                retry_count += 1
            
            # 检查是否所有重传都失败了
            if not ack_received:
                raise Exception(f"数据包 {sequence_num} 确认超时 (重传 {MAX_RETRIES} 次后失败).")
            
            # 更新循环变量
            bytes_sent += PACKET_PAYLOAD_SIZE
            sequence_num = (sequence_num + 1) % 256 # 序列号 (0-255) 自动回绕
        
        print("\n*** 成功！所有数据包发送完毕。 ***")
    
        # -----------------------------------------------------------------
        # --- 【新增】协议第8步：发送传输结束 (EOT) ---
        # -----------------------------------------------------------------
        print(f"\n--- 步骤 8: 发送传输结束 (EOT) (ID: 0x{HOST_REQUEST_ID_EOT:X}) ---")
        eot_payload = (c_ubyte * 8)(EOT_PACKET_ED, 0, 0, 0, 0, 0, 0, 0)
        if not send_can_message(zcan, chn_handle, HOST_REQUEST_ID_EOT, eot_payload, 8):
             raise Exception("发送EOT报文失败!")
        print(f" > 已发送EOT。")
        
        # -----------------------------------------------------------------
        # --- 【新增】协议第9步：等待最终校验结果 ---
        # -----------------------------------------------------------------
        print(f"\n--- 步骤 9: 等待MCU最终校验... (监听 0x{MCU_RESPONSE_ID_VERIFY_OK:X} / 0x{MCU_RESPONSE_ID_ERROR:X}) ---")
        
        verify_timeout = VERIFY_TIMEOUT_S
        start_time = time.time()
        final_result = None # None: 等待, True: 成功, False: 失败

        while time.time() - start_time < verify_timeout:
            rcv_num = zcan.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)
            if rcv_num > 0:
                rcv_msgs, act_num = zcan.Receive(chn_handle, rcv_num if rcv_num < 10 else 10)
                for i in range(act_num):
                    msg = rcv_msgs[i].frame
                    print(f" < 收到报文 ID: 0x{msg.can_id:X}")
                    
                    # 检查是否是“校验成功”报文
                    if msg.can_id == MCU_RESPONSE_ID_VERIFY_OK:
                        final_result = True
                        break
                    
                    # 检查是否是“失败重试”报文 (0xB0 或 0xB4)
                    if msg.can_id == MCU_RESPONSE_ID_BL_READY or msg.can_id == MCU_RESPONSE_ID_ERROR:
                        final_result = False
                        break
            if final_result is not None:
                break
            time.sleep(0.01)

        # 最终裁决
        if final_result == True:
            print("\n==============================================")
            print("  *** 固件更新成功! ***")
            print("  MCU正在重启进入新App...")
            print("==============================================")
        elif final_result == False:
            raise Exception("更新失败：MCU校验CRC不匹配，或报告了0xB4错误。")
        else: # final_result is None
            raise Exception(f"更新失败：等待MCU最终校验超时 ({verify_timeout}秒)。")


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