import time
from zlgcan import * # [cite: 137]
from isotp import IsoTpLayer

# 协议测试脚本

DEVICE_TYPE = ZCAN_USBCAN1
DEVICE_INDEX = 0
CHANNEL_INDEX = 0

def run_test():
    # 1. 启动 ZLG 设备 (复用你之前的逻辑)
    zcan = ZCAN()
    handle = zcan.OpenDevice(DEVICE_TYPE, DEVICE_INDEX, 0)
    if handle == INVALID_DEVICE_HANDLE:
        print("打开设备失败")
        return

    # 设置波特率 1Mbps
    zcan.ZCAN_SetValue(handle, "0/canfd_abit_baud_rate", "1000000")
    
    chn_cfg = ZCAN_CHANNEL_INIT_CONFIG()
    chn_cfg.can_type = ZCAN_TYPE_CAN
    chn_cfg.config.can.mode = 0
    
    chn_handle = zcan.InitCAN(handle, CHANNEL_INDEX, chn_cfg)
    zcan.StartCAN(chn_handle)
    
    print(f"CAN通道已启动, 句柄: {chn_handle}")

    # 2. 初始化 ISO-TP 层
    # 上位机发: 0x7E0,  MCU 回: 0x7E8
    tp = IsoTpLayer(zcan, chn_handle, tx_id=0x7E0, rx_id=0x7E8)

    try:
        # ==========================================
        # 测试 A: 发送单帧 (模拟 UDS 复位指令)
        # ==========================================
        print("\n--- 测试 A: 发送单帧 (UDS Reset) ---")
        # 0x11: ECUReset, 0x01: HardReset
        uds_reset = [0x11, 0x01] 
        if tp.send(uds_reset):
            print("单帧发送成功，请观察 MCU 是否重启。")
        else:
            print("单帧发送失败")

        time.sleep(2) # 等待一会儿

        # ==========================================
        # 测试 B: 发送长数据 (模拟 256 字节固件块)
        # ==========================================
        print("\n--- 测试 B: 发送长数据 (256 Bytes) ---")
        # 生成 00 01 02 ... FF 数据
        long_data = [i % 256 for i in range(256)]
        
        if tp.send(long_data):
            print("长数据发送成功！")
            print("请检查 MCU 调试变量 g_isotp.rx_buffer 是否完整接收。")
        else:
            print("长数据发送失败")

    except Exception as e:
        print(f"发生异常: {e}")

    finally:
        zcan.CloseDevice(handle)
        print("设备已关闭")

if __name__ == "__main__":
    run_test()