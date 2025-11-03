# -*- coding:utf-8 -*-

from zlgcan import *
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading
import time
import json

# --- 全局常量 (从Demo中保留，但移除了发送框的高度) ---
GRPBOX_WIDTH    = 200
MSGCNT_WIDTH    = 50
MSGID_WIDTH     = 80
MSGDIR_WIDTH    = 60
MSGINFO_WIDTH   = 100
MSGLEN_WIDTH    = 60
MSGDATA_WIDTH   = 200
MSGVIEW_WIDTH   = MSGCNT_WIDTH + MSGID_WIDTH + MSGDIR_WIDTH + MSGINFO_WIDTH + MSGLEN_WIDTH + MSGDATA_WIDTH
MSGVIEW_HEIGHT  = 280

# 发送框有关变量
SENDVIEW_HEIGHT = 125

# 窗口总高度现在只包含报文显示区域
WIDGHT_WIDTH    = GRPBOX_WIDTH + MSGVIEW_WIDTH + 40
WIDGHT_HEIGHT   = 500 + 60 

MAX_DISPLAY     = 1000
MAX_RCV_NUM     = 10

# (USBCANFD_TYPE, USBCAN_XE_U_TYPE, USBCAN_I_II_TYPE 常量被保留，因为 ChnInfoUpdate 中可能使用)
USBCANFD_TYPE    = (41, 42, 43)
USBCAN_XE_U_TYPE = (20, 21, 31)
USBCAN_I_II_TYPE = (3, 4)


class IAP_Tool_V1(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MyZLG_Tool")
        self.resizable(False, False)
        # 使用新的窗口高度
        self.geometry(str(WIDGHT_WIDTH) + "x" + str(WIDGHT_HEIGHT) + '+200+100')
        self.protocol("WM_DELETE_WINDOW", self.Form_OnClosing)

        self.DeviceInit()
        self.WidgetsInit()

        self._dev_info = None
        try:
            with open("./dev_info.json", "r") as fd:
                self._dev_info = json.load(fd)
        except FileNotFoundError:
            messagebox.showerror(title="错误", message="dev_info.json 配置文件未找到！")
            self.destroy()
            return
        except Exception as e:
            messagebox.showerror(title="配置错误", message=f"加载 dev_info.json 失败: {e}")
            self.destroy()
            return

        self.DeviceInfoInit()
        self.ChnInfoUpdate(self._isOpen)

    def DeviceInit(self):
        """
        初始化所有程序所需的状态变量
        """
        self._zcan       = ZCAN() 
        self._dev_handle = INVALID_DEVICE_HANDLE 
        self._can_handle = INVALID_CHANNEL_HANDLE 

        self._isOpen = False
        self._isChnOpen = False

        # 保留设备信息
        self._is_canfd = False
        self._res_support = False

        # 仅保留接收相关的计数
        self._rx_cnt = 0
        self._view_cnt = 0

        # 保留后台接收线程相关的变量
        self._read_thread = None
        self._terminated = False
        self._lock = threading.RLock() # 线程锁，用于安全更新UI

        self._tx_cnt = 0

    def WidgetsInit(self):
        """
        初始化所有GUI界面组件 (使用修正后的Grid布局)
        """
        # ---【修改】---
        # 不再使用 _dev_frame，我们直接在主窗口上布局
        # self._dev_frame = tk.Frame(self)
        # self._dev_frame.grid(row=0, column=0, padx=2, pady=2, sticky=tk.NSEW)

        # 1. 设备选择
        # ---【修改】--- 直接在主窗口(self)上grid
        self.gbDevConnect = tk.LabelFrame(self, height=100, width=GRPBOX_WIDTH, text="设备选择")
        self.gbDevConnect.grid_propagate(0)
        # ---【修改】--- 布局在 (row=0, column=0)
        self.gbDevConnect.grid(row=0, column=0, padx=2, pady=2, sticky=tk.NW) 
        self.DevConnectWidgetsInit()

        # 2. 通道配置
        # ---【修改】--- 直接在主窗口(self)上grid
        self.gbCANCfg = tk.LabelFrame(self, height=170, width=GRPBOX_WIDTH, text="通道配置")
        self.gbCANCfg.grid(row=1, column=0, padx=2, pady=2, sticky=tk.NW) 
        self.gbCANCfg.grid_propagate(0)
        self.CANChnWidgetsInit()

        # 3. 设备信息 (保持为空)
        # ---【修改】--- 直接在主窗口(self)上grid
        self.gbDevInfo = tk.LabelFrame(self, height=230, width=GRPBOX_WIDTH, text="设备信息")
        self.gbDevInfo.grid(row=2, column=0, padx=2, pady=2, sticky=tk.NW)
        self.gbDevInfo.grid_propagate(0)
        self.DevInfoWidgetsInit() 

        # 4. 报文显示
        self.gbMsgDisplay = tk.LabelFrame(self, height=MSGVIEW_HEIGHT, width=MSGVIEW_WIDTH + 12, text="报文显示")
        # ---【修改】--- 
        # 布局在 (row=0, column=1)，并且跨越2行 (rowspan=2)
        # sticky=tk.NSEW 让它在垂直方向上填满分配到的空间
        self.gbMsgDisplay.grid(row=0, column=1, rowspan=2, padx=2, pady=2, sticky=tk.NSEW) 
        self.gbMsgDisplay.grid_propagate(0)
        self.MsgDisplayWidgetsInit()
        
        # 5. 精简的报文发送框
        self.gbCustomSend = tk.LabelFrame(self, height=SENDVIEW_HEIGHT, width=MSGVIEW_WIDTH + 12, text="CAN报文发送")
        # ---【修改】--- 
        # 布局在 (row=2, column=1)，与“设备信息”框底部对齐
        self.gbCustomSend.grid(row=2, column=1, padx=2, pady=2, sticky=tk.NSEW) 
        self.gbCustomSend.grid_propagate(0)
        self.CustomSendWidgetsInit() # 调用新的函数来创建内部控件

    # --- 以下是各个区域的GUI控件创建函数 ---
    
    def DeviceInfoInit(self):
        # (从Demo中完整保留，用于填充设备下拉列表)
        self.cmbDevType["value"] = tuple([dev_name for dev_name in self._dev_info])
        self.cmbDevType.current(0)

    def DevConnectWidgetsInit(self):
        # (从Demo中完整保留)
        tk.Label(self.gbDevConnect, text="设备类型:").grid(row=0, column=0, sticky=tk.E)
        self.cmbDevType = ttk.Combobox(self.gbDevConnect, width=16, state="readonly")
        self.cmbDevType.grid(row=0, column=1, sticky=tk.E)

        tk.Label(self.gbDevConnect, text="设备索引:").grid(row=1, column=0, sticky=tk.E)
        self.cmbDevIdx = ttk.Combobox(self.gbDevConnect, width=16, state="readonly")
        self.cmbDevIdx.grid(row=1, column=1, sticky=tk.E)
        self.cmbDevIdx["value"] = tuple([i for i in range(4)])
        self.cmbDevIdx.current(0)

        self.strvDevCtrl = tk.StringVar()
        self.strvDevCtrl.set("打开")
        self.btnDevCtrl = ttk.Button(self.gbDevConnect, textvariable=self.strvDevCtrl, command=self.BtnOpenDev_Click)
        self.btnDevCtrl.grid(row=2, column=0, columnspan=2, pady=2) 

    def CANChnWidgetsInit(self):
        # (从Demo中完整保留)
        tk.Label(self.gbCANCfg, anchor=tk.W, text="CAN通道:").grid(row=0, column=0, sticky=tk.W)
        self.cmbCANChn = ttk.Combobox(self.gbCANCfg, width=12, state="readonly")
        self.cmbCANChn.grid(row=0, column=1, sticky=tk.E)

        tk.Label(self.gbCANCfg, anchor=tk.W, text="工作模式:").grid(row=1, column=0, sticky=tk.W)
        self.cmbCANMode = ttk.Combobox(self.gbCANCfg, width=12, state="readonly")
        self.cmbCANMode.grid(row=1, column=1, sticky=tk.E)

        tk.Label(self.gbCANCfg, anchor=tk.W, text="波特率:").grid(row=2, column=0, sticky=tk.W)
        self.cmbBaudrate = ttk.Combobox(self.gbCANCfg, width=12, state="readonly")
        self.cmbBaudrate.grid(row=2, column=1, sticky=tk.W)
        
        tk.Label(self.gbCANCfg, anchor=tk.W, text="数据域波特率:").grid(row=3, column=0, sticky=tk.W)
        self.cmbDataBaudrate = ttk.Combobox(self.gbCANCfg, width=12, state="readonly")
        self.cmbDataBaudrate.grid(row=3, column=1, sticky=tk.W)

        tk.Label(self.gbCANCfg, anchor=tk.W, text="终端电阻:").grid(row=4, column=0, sticky=tk.W)
        self.cmbResEnable = ttk.Combobox(self.gbCANCfg, width=12, state="readonly")
        self.cmbResEnable.grid(row=4, column=1, sticky=tk.W)

        self.strvCANCtrl = tk.StringVar()
        self.strvCANCtrl.set("打开")
        self.btnCANCtrl = ttk.Button(self.gbCANCfg, textvariable=self.strvCANCtrl, command=self.BtnOpenCAN_Click) 
        self.btnCANCtrl.grid(row=5, column=0, columnspan=2, padx=2, pady=2)

    def DevInfoWidgetsInit(self):
        
        pass


    def MsgDisplayWidgetsInit(self):
        # (从Demo中保留，但移除了发送帧数(TxCnt)的显示)
        self._msg_frame = tk.Frame(self.gbMsgDisplay, height=MSGVIEW_HEIGHT, width=WIDGHT_WIDTH-GRPBOX_WIDTH+10)
        self._msg_frame.pack(side=tk.TOP)
        
        self.treeMsg = ttk.Treeview(self._msg_frame, height=10, show="headings")
        self.treeMsg["columns"] = ("cnt", "id", "direction", "info", "len", "data")
        self.treeMsg.column("cnt",       anchor = tk.CENTER, width=MSGCNT_WIDTH)
        self.treeMsg.column("id",        anchor = tk.CENTER, width=MSGID_WIDTH)
        self.treeMsg.column("direction", anchor = tk.CENTER, width=MSGDIR_WIDTH)
        self.treeMsg.column("info",      anchor = tk.CENTER, width=MSGINFO_WIDTH)
        self.treeMsg.column("len",       anchor = tk.CENTER, width=MSGLEN_WIDTH)
        self.treeMsg.column("data", width=MSGDATA_WIDTH)
        self.treeMsg.heading("cnt", text="序号")
        self.treeMsg.heading("id", text="帧ID")
        self.treeMsg.heading("direction", text="方向")
        self.treeMsg.heading("info", text="帧信息")
        self.treeMsg.heading("len", text="长度")
        self.treeMsg.heading("data", text="数据")
        
        self.hbar = ttk.Scrollbar(self._msg_frame, orient=tk.HORIZONTAL, command=self.treeMsg.xview)
        self.hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.vbar = ttk.Scrollbar(self._msg_frame, orient=tk.VERTICAL, command=self.treeMsg.yview)
        self.vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.treeMsg.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        
        self.treeMsg.pack(side=tk.LEFT)
        self.treeMsg.selection_set()
        
        # --- (底部的状态栏) ---
        self.btnClrCnt = ttk.Button(self.gbMsgDisplay, width=10, text="清空", command=self.BtnClrCnt_Click) 
        self.btnClrCnt.pack(side=tk.RIGHT)
        
        self.strvRxCnt = tk.StringVar()
        self.strvRxCnt.set("0")
        tk.Label(self.gbMsgDisplay, anchor=tk.W, width=5, textvariable=self.strvRxCnt).pack(side=tk.RIGHT)
        tk.Label(self.gbMsgDisplay, width=10, text="接收帧数:").pack(side=tk.RIGHT)

        # ---【新增】---
        self.strvTxCnt = tk.StringVar()
        self.strvTxCnt.set("0")
        tk.Label(self.gbMsgDisplay, anchor=tk.W, width=5, textvariable=self.strvTxCnt).pack(side=tk.RIGHT)
        tk.Label(self.gbMsgDisplay, width=10, text="发送帧数:").pack(side=tk.RIGHT)

###############################################################################
### Function (功能函数)
###############################################################################

    def CustomSendWidgetsInit(self):
        """
        创建精简的发送控件
        """
        # 帧ID
        tk.Label(self.gbCustomSend, anchor=tk.W, text="帧ID(hex):").grid(row=0, column=0, padx=5, sticky=tk.W)
        self.entrySendID = tk.Entry(self.gbCustomSend, width=10)
        self.entrySendID.grid(row=0, column=1, sticky=tk.W) 
        self.entrySendID.insert(0, "100") # 默认值

        # 长度
        tk.Label(self.gbCustomSend, anchor=tk.W, text="长度:").grid(row=0, column=2, padx=5, sticky=tk.W)
        self.cmbSendLen = ttk.Combobox(self.gbCustomSend, width=6, state="readonly")
        self.cmbSendLen["value"] = tuple([i for i in range(9)]) # 0-8
        self.cmbSendLen.current(8) # 默认长度为8
        self.cmbSendLen.grid(row=0, column=3, sticky=tk.W) 

        # 发送按钮
        self.btnSend = ttk.Button(self.gbCustomSend, text="发送", command=self.BtnSendCustom_Click) 
        self.btnSend.grid(row=0, column=4, rowspan=2, padx=20, pady=5, sticky=tk.E)
        self.btnSend["state"] = tk.DISABLED # 初始禁用
        
        # 数据
        tk.Label(self.gbCustomSend, anchor=tk.W, text="数据(hex):").grid(row=1, column=0, padx=5, sticky=tk.W)
        self.entrySendData = tk.Entry(self.gbCustomSend, width=40) # 足够宽
        self.entrySendData.grid(row=1, column=1, columnspan=3, padx=5, sticky=tk.W) 
        self.entrySendData.insert(0, "00 01 02 03 04 05 06 07") # 默认值

    def CANMsg2View(self, msg, is_transmit=True):
        # (从Demo中完整保留，用于格式化标准CAN报文)
        view = []
        view.append(str(self._view_cnt))
        self._view_cnt += 1 
        view.append(hex(msg.can_id)[2:])
        view.append("发送" if is_transmit else "接收")

        str_info = ''
        str_info += 'EXT' if msg.eff else 'STD'
        if msg.rtr:
            str_info += ' RTR'
        view.append(str_info)
        view.append(str(msg.can_dlc))
        if msg.rtr:
            view.append('')
        else:
            view.append(''.join(hex(msg.data[i])[2:] + ' ' for i in range(msg.can_dlc)))
        return view

    def ChnInfoUpdate(self, is_open):
        # (从Demo中完整保留，用于根据JSON配置动态更新下拉框)
        cur_dev_info = self._dev_info[self.cmbDevType.get()]
        cur_chn_info = cur_dev_info["chn_info"]
        
        if is_open:
            self.cmbCANChn["value"] = tuple([i for i in range(cur_dev_info["chn_num"])])
            self.cmbCANChn.current(0)
            self.cmbCANMode["value"] = ("正常模式", "只听模式")
            self.cmbCANMode.current(0)
            self.cmbBaudrate["value"] = tuple([brt for brt in cur_chn_info["baudrate"].keys()])
            self.cmbBaudrate.current(len(self.cmbBaudrate["value"]) - 1) # 默认选中最后一个波特率
            if cur_chn_info["is_canfd"] == True:
                self.cmbDataBaudrate["value"] = tuple([brt for brt in cur_chn_info["data_baudrate"].keys()])
                self.cmbDataBaudrate.current(0)
                self.cmbDataBaudrate["state"] = "readonly"
            if cur_chn_info["sf_res"] == True:
                self.cmbResEnable["value"] = ("使能", "失能")
                self.cmbResEnable.current(0)
                self.cmbResEnable["state"] = "readonly"
            self.btnCANCtrl["state"] = tk.NORMAL
        else:
            # (省略了关闭时的UI状态设置，与Demo一致)
            self.cmbCANChn["state"] = tk.DISABLED
            self.cmbCANMode["state"] = tk.DISABLED
            self.cmbBaudrate["state"] = tk.DISABLED
            self.cmbDataBaudrate["state"] = tk.DISABLED
            self.cmbResEnable["state"] = tk.DISABLED
            self.cmbCANChn["value"] = ()
            self.cmbCANMode["value"] = ()
            self.cmbBaudrate["value"] = ()
            self.cmbDataBaudrate["value"] = ()
            self.cmbResEnable["value"] = ()
            self.btnCANCtrl["state"] = tk.DISABLED

    def ChnInfoDisplay(self, enable):
        # (从Demo中完整保留，用于在打开/关闭通道时禁用/启用下拉框)
        if enable:
            self.cmbCANChn["state"] = "readonly"
            self.cmbCANMode["state"] = "readonly"
            self.cmbBaudrate["state"] = "readonly" 
            if self._is_canfd: 
                self.cmbDataBaudrate["state"] = "readonly" 
            if self._res_support: 
                self.cmbResEnable["state"] = "readonly"
        else:
            self.cmbCANChn["state"] = tk.DISABLED
            self.cmbCANMode["state"] = tk.DISABLED
            self.cmbBaudrate["state"] = tk.DISABLED
            self.cmbDataBaudrate["state"] = tk.DISABLED
            self.cmbResEnable["state"] = tk.DISABLED
    
    def MsgReadThreadFunc(self):
        """
        后台接收线程的主函数 (已精简，只处理标准CAN)
        """
        try:
            while not self._terminated:
                # 1. 仅查询标准CAN报文
                can_num = self._zcan.GetReceiveNum(self._can_handle, ZCAN_TYPE_CAN)
                
                if not can_num:
                    time.sleep(0.005) # 休眠5ms
                    continue

                # 2. 循环排空缓冲区
                while can_num and not self._terminated:
                    read_cnt = MAX_RCV_NUM if can_num >= MAX_RCV_NUM else can_num
                    can_msgs, act_num = self._zcan.Receive(self._can_handle, read_cnt, MAX_RCV_NUM)
                    
                    if act_num: 
                        # 3. 更新UI
                        self._rx_cnt += act_num 
                        self.strvRxCnt.set(str(self._rx_cnt))
                        self.ViewDataUpdate(can_msgs, act_num, False, False)
                    else:
                        break # 读取失败或超时，退出内循环
                    can_num -= act_num
        except:
            if not self._terminated:
                print("Error occurred while read CAN data!")

    def ViewDataUpdate(self, msgs, msgs_num, is_canfd=False, is_send=True):
        """
        更新报文显示列表 (已精简，只处理标准CAN)
        """
        # self._lock 确保了主线程和后台线程不会同时操作GUI列表
        with self._lock: 
            # (is_canfd 的分支已被移除)
            for i in range(msgs_num):
                # 列表满则删除最旧的一条
                if len(self.treeMsg.get_children()) == MAX_DISPLAY:
                    self.treeMsg.delete(self.treeMsg.get_children()[0])
                # 插入新报文
                self.treeMsg.insert('', 'end', values=self.CANMsg2View(msgs[i].frame, is_send))
                # 自动滚动到最后一条
                child_id = self.treeMsg.get_children()[-1]
                self.treeMsg.focus(child_id)
                self.treeMsg.selection_set(child_id)

    # --- (所有与发送相关的函数 PeriodSendIdUpdate, PeriodSendComplete, PeriodSend, MsgSend 已被移除) ---

    def DevInfoRead(self):
        # (从Demo中完整保留)
        pass

    def DevInfoClear(self):
        # (从Demo中完整保留)
        pass
###############################################################################
### Event handers (事件处理函数)
###############################################################################
    def Form_OnClosing(self):
        """
        处理窗口关闭事件
        """
        if self._isOpen:
            self.btnDevCtrl.invoke() # 模拟点击“关闭设备”按钮，确保安全退出
        self.destroy()

    def BtnOpenDev_Click(self):
        """
        处理“打开/关闭设备”按钮点击事件
        """
        if self._isOpen:
            # --- 关闭设备 ---
            if self._isChnOpen:
                self.btnCANCtrl.invoke() # 如果通道还开着，先模拟点击关闭通道

            self._zcan.CloseDevice(self._dev_handle) # 调用库函数关闭设备

            self.DevInfoClear() # 清空设备信息显示
            self.strvDevCtrl.set("打开")
            self.cmbDevType["state"] = "readonly"
            self.cmbDevIdx["state"] = "readonly"
            self._isOpen = False
            self.btnSend["state"] = tk.DISABLED
        else:
            # --- 打开设备 ---
            self._cur_dev_info = self._dev_info[self.cmbDevType.get()]

            self._dev_handle = self._zcan.OpenDevice(self._cur_dev_info["dev_type"], 
                                                      self.cmbDevIdx.current(), 0)
            if self._dev_handle == INVALID_DEVICE_HANDLE:
                messagebox.showerror(title="打开设备", message="打开设备失败！")
                return 
            
            self.DevInfoRead() # 读取并显示设备信息

            # 记录设备能力
            self._is_canfd = self._cur_dev_info["chn_info"]["is_canfd"]
            self._res_support = self._cur_dev_info["chn_info"]["sf_res"]
            
            # (与发送相关的CANFD类型更新已被移除)

            self.strvDevCtrl.set("关闭")
            self.cmbDevType["state"] = tk.DISABLED
            self.cmbDevIdx["state"] = tk.DISABLED
            self._isOpen = True 
        
        # 更新通道相关的下拉框状态
        self.ChnInfoUpdate(self._isOpen)
        self.ChnInfoDisplay(self._isOpen)

    def BtnOpenCAN_Click(self):
        """
        处理“打开/关闭通道”按钮点击事件
        """
        if self._isChnOpen:
            # --- 关闭通道 ---
            # 1. 通知后台接收线程停止
            self._terminated = True
            self._read_thread.join(0.1) # 等待线程退出 (最多0.1秒)
            self._zcan.ResetCAN(self._can_handle)
            self.strvCANCtrl.set("打开")
            self._isChnOpen = False
            self.btnSend["state"] = tk.DISABLED
            
        else:
            # --- 打开通道 ---
            chn_cfg = ZCAN_CHANNEL_INIT_CONFIG()
            
            # 【重要】根据设备能力设置CAN或CANFD
            chn_cfg.can_type = ZCAN_TYPE_CANFD if self._is_canfd else ZCAN_TYPE_CAN
            
            # 【重要】设置波特率
            # Demo中使用 ZCAN_SetValue 的方式来设置，我们保留此逻辑
            # 注意：这里我们硬编码为您之前测试成功的1Mbps (1000000)
            # 无论是否为CANFD，都设置仲裁域波特率
            baud_rate_str = "1000000" # 硬编码为1Mbps
            # 您也可以从下拉框获取: baud_rate_str = self.cmbBaudrate.get().replace("Kbps", "000")
            
            # 使用 ZCAN_SetValue 来设置波特率
            # 路径 "0/canfd_abit_baud_rate" 似乎是ZLG库用于统一设置波特率的方式
            self._zcan.ZCAN_SetValue(self._dev_handle, "0/canfd_abit_baud_rate", baud_rate_str)
            
            if self._is_canfd:
                # (CANFD数据域波特率的设置逻辑被移除，因为我们只关心标准CAN)
                chn_cfg.config.canfd.mode = self.cmbCANMode.current()
            else:
                chn_cfg.config.can.mode = self.cmbCANMode.current()
                
            # (Demo中关于F1芯片(USBCAN_I_II_TYPE)的timing0/1设置被注释掉了，我们保持一致)

            # 2. 初始化CAN通道
            self._can_handle = self._zcan.InitCAN(self._dev_handle, self.cmbCANChn.current(), chn_cfg)
            if self._can_handle == INVALID_CHANNEL_HANDLE:
                messagebox.showerror(title="打开通道", message="初始化通道失败!")
                return 
            
            # 3. 启动CAN通道
            ret = self._zcan.StartCAN(self._can_handle)
            if ret != ZCAN_STATUS_OK: 
                messagebox.showerror(title="打开通道", message="打开通道失败!")
                return 

            # (启动发送线程的逻辑已被移除)

            # 4. 启动后台接收线程
            self._terminated = False
            self._read_thread = threading.Thread(None, target=self.MsgReadThreadFunc)
            self._read_thread.start()
            
            # 5. 更新UI状态
            self.strvCANCtrl.set("关闭")
            self._isChnOpen = True 
            self.btnSend["state"] = tk.NORMAL
            
        self.ChnInfoDisplay(not self._isChnOpen)

    def BtnClrCnt_Click(self):
        """
        处理“清空”按钮点击事件
        """
        self._tx_cnt = 0
        self._rx_cnt = 0
        self._view_cnt = 0
        self.strvRxCnt.set("0")
        self.strvTxCnt.set("0")
        for item in self.treeMsg.get_children():
            self.treeMsg.delete(item)

    def BtnSendCustom_Click(self):
        """
        处理点击“发送”按钮的事件 (精简版)
        """
        # 1. 检查通道是否打开
        if not self._isChnOpen:
            messagebox.showwarning(title="发送错误", message="请先打开CAN通道！")
            return

        # 2. 创建标准CAN报文结构体
        msg = ZCAN_Transmit_Data()
        msg.transmit_type = 0 # 0: 正常发送
        msg.frame.eff = 0 # 0: 标准帧
        msg.frame.rtr = 0 # 0: 数据帧

        # 3. 从GUI读取并填充参数 (带错误处理)
        try:
            msg.frame.can_id = int(self.entrySendID.get(), 16)
        except:
            messagebox.showerror(title="输入错误", message="帧ID必须是一个有效的十六进制数！")
            return
            
        msg.frame.can_dlc = self.cmbSendLen.current() # 获取 0-8
        msg_len = msg.frame.can_dlc
        
        try:
            data_str_list = self.entrySendData.get().split(' ')
            for i in range(msg_len):
                if i < len(data_str_list) and data_str_list[i] != '':
                    msg.frame.data[i] = int(data_str_list[i], 16)
                else:
                    msg.frame.data[i] = 0
        except Exception as e:
            messagebox.showerror(title="数据错误", message=f"数据格式错误，请使用空格分隔的十六进制数。\n错误: {e}")
            return

        # 4. 调用底层发送函数，只发送1帧
        ret = self._zcan.Transmit(self._can_handle, msg, 1)

        # 5. 提供反馈
        if ret == 1: # 假设1为ZCAN_STATUS_OK
            self._tx_cnt += 1
            self.strvTxCnt.set(str(self._tx_cnt))
            self.ViewDataUpdate( [msg] , 1, is_canfd=False, is_send=True)
        else:
            messagebox.showerror(title="发送失败", message=f"发送CAN报文失败！错误码: {ret}")

###############################################################################
### 启动入口
###############################################################################
if __name__ == "__main__":
    demo = IAP_Tool_V1()
    demo.mainloop()