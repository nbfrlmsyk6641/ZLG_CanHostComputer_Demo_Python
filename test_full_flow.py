import time
from zlgcan import *
from isotp import IsoTpLayer

# 测试App端UDS服务的脚本
# 测试的UDS服务包括:
# 1、请求进入默认对话
# 2、请求进入扩展对话
# 3、请求进行预编程条件检查
# 4、请求进入编程对话
# 5、验证MCU对非法操作的拒绝响应

DEVICE_TYPE = ZCAN_USBCAN1
DEVICE_INDEX = 0
CHANNEL_INDEX = 0

TX_ID = 0x7E0 # 上位机请求 CAN ID
RX_ID = 0x7E8 # MCU 响应 CAN ID


def wait_uds_response(zcan, chn_handle, timeout=2.0):
    """
    简单的等待 UDS 响应函数 (仅支持接收单帧 SF，因为测试App部分的代码主要是单帧交互)
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        num = zcan.GetReceiveNum(chn_handle, ZCAN_TYPE_CAN)
        if num > 0:
            msgs, cnt = zcan.Receive(chn_handle, num)
            for i in range(cnt):
                msg = msgs[i].frame
                if msg.can_id == RX_ID:
                    # 简单解析 ISO-TP 单帧 (SF)
                    # Byte 0: [PCI(4bit) | Len(4bit)]
                    if (msg.data[0] & 0xF0) == 0x00:
                        length = msg.data[0] & 0x0F
                        # 返回有效数据部分
                        return list(msg.data[1 : 1+length])
        time.sleep(0.005)
    return None

def print_result(step_name, passed, detail=""):
    if passed:
        print(f"[PASS] {step_name}: {detail}")
    else:
        print(f"[FAIL] {step_name}: {detail}")
        # exit(0) # 也可以选择失败即退出


def run_test():
    # 1. 初始化硬件
    zcan = ZCAN()
    handle = zcan.OpenDevice(DEVICE_TYPE, DEVICE_INDEX, 0)
    if handle == INVALID_DEVICE_HANDLE:
        print("打开设备失败")
        return

    print("--- 硬件初始化成功 ---")
    zcan.ZCAN_SetValue(handle, "0/canfd_abit_baud_rate", "1000000")
    chn_cfg = ZCAN_CHANNEL_INIT_CONFIG()
    chn_cfg.can_type = ZCAN_TYPE_CAN
    chn_cfg.config.can.mode = 0
    chn_handle = zcan.InitCAN(handle, CHANNEL_INDEX, chn_cfg)
    zcan.StartCAN(chn_handle)

    # 2. 初始化发送层（ISO-TP）协议
    tp = IsoTpLayer(zcan, chn_handle, TX_ID, RX_ID)

    try:
        # 测试 1: 违规操作 - 直接请求编程会话 (10 02)
        # 预期: MCU 拒绝
        print("\n>>> 测试 1: 直接请求编程会话 (Expect: Failure)")
        tp.send([0x10, 0x02]) # DiagnosticSessionControl - Programming
        
        resp = wait_uds_response(zcan, chn_handle)
        if resp and resp[0] == 0x7F and resp[2] == 0x22:
            print_result("Test 1", True, f"MCU 正确拒绝 (NRC={resp[2]:02X})")
        elif resp and resp[0] == 0x50:
            print_result("Test 1", False, "MCU 同意！逻辑有漏洞！")
        else:
            print_result("Test 1", False, f"响应未知: {[hex(x) for x in resp] if resp else 'None'}")

        time.sleep(0.5)

        # 测试 2: 正常操作 - 进入扩展会话 (10 03)
        # 预期: MCU 同意 (50 03 ...)
        print("\n>>> 测试 2: 进入扩展会话 (Expect: Success)")
        tp.send([0x10, 0x03]) # DiagnosticSessionControl - Extended
        
        resp = wait_uds_response(zcan, chn_handle)
        if resp and resp[0] == 0x50 and resp[1] == 0x03:
            print_result("Test 2", True, "成功进入扩展会话")
        else:
            print_result("Test 2", False, f"进入扩展会话失败: {[hex(x) for x in resp] if resp else 'None'}")

        time.sleep(0.5)

        # 测试 3: 违规操作 - 未做检查直接进编程 (10 02)
        # 预期: MCU 拒绝 (NRC 0x22 条件不满足)
        print("\n>>> 测试 3: 未预检请求编程 (Expect: Failure)")
        tp.send([0x10, 0x02]) 
        
        resp = wait_uds_response(zcan, chn_handle)
        if resp and resp[0] == 0x7F and resp[2] == 0x22:
            print_result("Test 3", True, f"MCU 正确拒绝 (NRC={resp[2]:02X})")
        elif resp and resp[0] == 0x50:
            print_result("Test 3", False, "MCU 同意！逻辑有漏洞！")
        else:
            print_result("Test 3", False, f"响应未知: {[hex(x) for x in resp] if resp else 'None'}")

        time.sleep(0.5)

        # 测试 4: 正常操作 - 预编程条件检查 (31 01 FF 00)
        # 预期: MCU 同意 (71 01 FF 00)
        print("\n>>> 测试 4: 执行预编程检查 (Expect: Success)")
        tp.send([0x31, 0x01, 0xFF, 0x00]) # RoutineControl - Start - CheckRoutine
        
        resp = wait_uds_response(zcan, chn_handle)
        if resp and resp[0] == 0x71 and resp[1] == 0x01:
            print_result("Test 4", True, "预编程检查通过")
        else:
            print_result("Test 4", False, f"检查失败: {[hex(x) for x in resp] if resp else 'None'}")

        time.sleep(0.5)

        # 测试 5: 最终操作 - 再次请求编程会话 (10 02)
        # 预期: MCU 同意 (50 02) 并重启
        print("\n>>> 测试 5: 请求编程并跳转 (Expect: Success & Reset)")
        tp.send([0x10, 0x02]) 
        
        resp = wait_uds_response(zcan, chn_handle)
        if resp and resp[0] == 0x50 and resp[1] == 0x02:
            print_result("Test 5", True, "成功！MCU 正在重启进入 Bootloader...")
        else:
            print_result("Test 5", False, f"跳转失败: {[hex(x) for x in resp] if resp else 'None'}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        zcan.CloseDevice(handle)

if __name__ == "__main__":
    run_test()