import requests
import json
import os
import binascii
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sys
from tkinter import font
import subprocess
import threading
import time
import logging
import socket  # 新增：导入socket模块（修复NameError）

# 尝试导入Pillow库
try:
    from PIL import Image, ImageTk, ImageDraw
    import io

    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

# 尝试导入托盘支持库
try:
    import pystray
    from pystray import MenuItem as item

    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False

# Windows系统自启动需要的模块
if sys.platform.startswith('win'):
    import winreg


class ScrollableFrame(ttk.Frame):
    """带垂直滚动条的可滚动框架"""

    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class NetworkLoginApp:
    def __init__(self, root):
        self.root = root
        self.root.geometry("900x600")
        self.root.minsize(800, 500)
        self.root.title("校园网认证工具")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # 获取程序所在目录（关键修改点）
        self.app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

        # 在初始化早期定义root_active
        self.root_active = True  # 跟踪主窗口是否活跃

        # 配置日志记录
        self.setup_logging()
        self.logger.info("程序启动")

        # 字体设置
        self.default_font = font.nametofont("TkDefaultFont")
        self.default_font.configure(family="Microsoft YaHei", size=10)
        self.subtitle_font = font.Font(family="Microsoft YaHei", size=12, weight="bold")

        # 网络监控相关变量 - 提前初始化
        self.monitoring = False
        self.monitor_thread = None
        self.ping_interval = 60  # 秒
        self.check_sites = ["www.baidu.com", "qq.com", "www.taobao.com"]  # 增加更多检测网站
        self.initial_network_check_attempts = 0  # 初始网络检查尝试次数
        self.max_initial_check_attempts = 12  # 最大尝试次数（12次 * 5秒 = 60秒）
        self.initial_check_delay = 5  # 每次检查间隔（秒）

        # 自启动配置
        self.auto_start = False
        self.auto_start_key = "CampusNetworkLogin"
        self.auto_start_path = os.path.abspath(sys.argv[0])  # 获取当前程序路径
        self.load_auto_start_status()  # 加载自启动状态

        # 使用程序目录下的配置文件
        self.config_file = os.path.join(self.app_dir, "login_config.ini")
        self.config = {}
        self.scrollable_frame = ScrollableFrame(self.root)
        self.scrollable_frame.grid(row=0, column=0, sticky="nsew")
        self.scrollable_frame.grid_rowconfigure(0, weight=1)
        self.scrollable_frame.grid_columnconfigure(0, weight=1)

        self.create_widgets()

        # 自动登录检查
        if self.load_config():
            self.root.after(100, self.auto_login)
            # 确保在root_active设置后再启动监控
            if self.root_active:
                self.start_network_monitor()  # 启动网络监控

        # 初始化系统托盘
        self.tray = None
        self.tray_active = False  # 跟踪托盘是否处于活动状态
        self.init_system_tray()

    def setup_logging(self):
        """配置日志记录"""
        # 使用已获取的程序目录
        log_file = os.path.join(self.app_dir, "app.log")

        self.logger = logging.getLogger("CampusNetworkLogin")
        self.logger.setLevel(logging.INFO)

        # 创建文件处理器
        os.makedirs(self.app_dir, exist_ok=True)  # 确保目录存在
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)

        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 创建日志格式
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # 添加处理器
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def init_system_tray(self):
        """初始化系统托盘图标"""
        if not (PYSTRAY_AVAILABLE and PILLOW_AVAILABLE):
            self.logger.warning("系统托盘功能不可用，缺少pystray或Pillow库")
            return

        try:
            # 创建托盘菜单
            menu = (
                item("显示窗口", self.show_window),
                item("退出程序", self.quit_app)
            )

            # 使用程序目录下的图标
            icon_path = os.path.join(self.app_dir, "icon.ico")  # 假设图标文件与程序在同一目录
            if os.path.exists(icon_path):
                icon = Image.open(icon_path)
                self.logger.info(f"成功加载托盘图标: {icon_path}")
            else:
                # 如果找不到指定图标，则创建默认图标
                self.logger.warning(f"找不到图标文件: {icon_path}，使用默认图标")
                icon = Image.new("RGB", (32, 32), color=(50, 150, 250))
                draw = ImageDraw.Draw(icon)
                draw.ellipse((2, 2, 30, 30), fill=(20, 100, 200))  # 蓝色圆形图标
                draw.text((8, 8), "📶", fill="white")  # 添加信号图标

            self.tray = pystray.Icon("CampusLogin", icon, "校园网认证", menu)
            self.tray.menu = menu

            # 绑定窗口关闭事件
            self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)

            # 启动托盘线程
            self.tray_thread = threading.Thread(target=self._run_tray, daemon=True)
            self.tray_thread.start()
            self.logger.info("系统托盘初始化成功")
        except Exception as e:
            self.logger.error(f"系统托盘初始化失败: {str(e)}")

    def _run_tray(self):
        """运行托盘图标并设置活动标志"""
        try:
            self.tray_active = True
            self.tray.run()
        except Exception as e:
            self.logger.error(f"托盘运行时出错: {str(e)}")
        finally:
            self.tray_active = False
            self.logger.info("托盘图标已停止")

    def on_window_close(self):
        """处理窗口关闭事件"""
        if self.tray and self.tray_active and self.root_active:
            self.logger.info("窗口最小化到系统托盘")
            self.root.withdraw()  # 隐藏主窗口
            self.tray.visible = True  # 显示托盘图标
        else:
            self.quit_app()

    def show_window(self):
        """显示主窗口"""
        if self.tray and self.tray_active and self.root_active:
            self.tray.visible = False
        self.logger.info("从系统托盘恢复窗口")
        if self.root_active:  # 检查窗口是否已销毁
            self.root.deiconify()

    def quit_app(self):
        """退出应用程序"""
        try:
            self.logger.info("用户请求退出程序")
            self.root_active = False  # 标记窗口已销毁

            if self.tray and self.tray_active:
                self.tray.stop()

            if self.monitoring:
                self.monitoring = False

            self.root.destroy()
            sys.exit(0)
        except Exception as e:
            self.logger.error(f"退出程序时发生错误: {str(e)}")
            messagebox.showerror("退出错误", f"退出程序时发生错误：{str(e)}")
            sys.exit(1)

    def create_widgets(self):
        """创建界面组件"""
        main_frame = ttk.Frame(self.scrollable_frame.scrollable_frame, padding=10)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        self.tab_control = ttk.Notebook(main_frame)
        self.tab_control.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.tab_control.grid_rowconfigure(0, weight=1)
        self.tab_control.grid_columnconfigure(0, weight=1)

        self.tab_config = ttk.Frame(self.tab_control)
        self.tab_result = ttk.Frame(self.tab_control)
        self.tab_tutorial = ttk.Frame(self.tab_control)
        self.tab_status = ttk.Frame(self.tab_control)  # 新增状态标签页

        self.tab_control.add(self.tab_config, text="配置")
        self.tab_control.add(self.tab_result, text="结果")
        self.tab_control.add(self.tab_tutorial, text="使用教程")
        self.tab_control.add(self.tab_status, text="网络状态")

        self.create_config_tab()
        self.create_result_tab()
        self.create_tutorial_tab()
        self.create_status_tab()

    def create_config_tab(self):
        """配置页面"""
        frame = ttk.Frame(self.tab_config, padding=20)
        frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        frame.grid_rowconfigure(10, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        left_frame = ttk.Frame(frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right_frame = ttk.Frame(frame)
        right_frame.grid(row=0, column=1, sticky="ns", padx=(10, 0))

        left_frame.grid_rowconfigure(10, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        # 用户账号
        ttk.Label(left_frame, text="用户账号:", font=self.subtitle_font).grid(row=0, column=0, sticky="w", pady=5)
        self.user_account = ttk.Entry(left_frame, width=50, font=self.default_font)
        self.user_account.grid(row=1, column=0, sticky="ew", pady=15)
        left_frame.grid_rowconfigure(1, weight=1)

        # 加密密码
        ttk.Label(left_frame, text="加密密码:", font=self.subtitle_font).grid(row=2, column=0, sticky="w", pady=5)
        self.encrypted_password = scrolledtext.ScrolledText(left_frame, width=50, height=4, font=self.default_font)
        self.encrypted_password.grid(row=3, column=0, sticky="ew", pady=15)
        left_frame.grid_rowconfigure(3, weight=1)

        # 服务提供商
        ttk.Label(left_frame, text="服务提供商:", font=self.subtitle_font).grid(row=4, column=0, sticky="w", pady=5)
        self.service_name = tk.StringVar(value="cmcc")
        service_frame = ttk.Frame(left_frame)
        service_frame.grid(row=5, column=0, sticky="w", pady=15)
        ttk.Radiobutton(service_frame, text="中国移动宽带", variable=self.service_name, value="cmcc",
                        style="TRadiobutton").pack(anchor="w", pady=2)
        ttk.Radiobutton(service_frame, text="中国电信宽带", variable=self.service_name, value="telecom",
                        style="TRadiobutton").pack(anchor="w", pady=2)
        left_frame.grid_rowconfigure(5, weight=1)

        # 网络参数
        ttk.Label(left_frame, text="网络参数 (networkParams):", font=self.subtitle_font).grid(row=6, column=0,
                                                                                              sticky="w", pady=5)
        self.network_params = scrolledtext.ScrolledText(left_frame, width=50, height=6, font=self.default_font)
        self.network_params.grid(row=7, column=0, sticky="ew", pady=20)
        left_frame.grid_rowconfigure(7, weight=1)

        # 自启动设置
        ttk.Label(left_frame, text="自启动设置:", font=self.subtitle_font).grid(row=8, column=0, sticky="w", pady=5)
        self.auto_start_var = tk.IntVar(value=self.auto_start)
        ttk.Checkbutton(left_frame, text="开机自动启动", variable=self.auto_start_var,
                        command=self.toggle_auto_start, style="TCheckbutton").grid(row=9, column=0, sticky="w", pady=5)
        left_frame.grid_rowconfigure(9, weight=1)

        # 功能按钮
        btn_frame = ttk.Frame(left_frame)
        btn_frame.grid(row=10, column=0, sticky="ew", pady=10)
        ttk.Button(btn_frame, text="保存配置并登录", command=self.save_config_and_login, style="TButton").pack(
            side="left", padx=5)
        ttk.Button(btn_frame, text="重置配置", command=self.reset_config, style="TButton").pack(side="left", padx=5)
        ttk.Button(btn_frame, text="查看教程", command=lambda: self.tab_control.select(2), style="TButton").pack(
            side="left", padx=5)
        left_frame.grid_rowconfigure(10, weight=1)

        # 右侧提示信息
        ttk.Separator(right_frame, orient="vertical").pack(fill="y", padx=10)
        info_frame = ttk.LabelFrame(right_frame, text="提示信息", padding=10)
        info_frame.pack(fill="y", expand=True)
        info_text = """
请输入网络登录所需的配置信息：
1. 用户账号：通常为学号或工号
2. 加密密码：从浏览器开发者工具中获取
3. 服务提供商：选择对应的网络服务
4. 网络参数：从登录请求中提取的参数
点击"保存配置并登录"按钮完成操作。
"""
        ttk.Label(info_frame, text=info_text, font=self.default_font, justify="left").pack(fill="both", expand=True)

    def create_result_tab(self):
        """结果页面"""
        frame = ttk.Frame(self.tab_result, padding=20)
        frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        frame.grid_rowconfigure(3, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        left_frame = ttk.Frame(frame)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right_frame = ttk.Frame(frame)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        left_frame.grid_rowconfigure(3, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)
        right_frame.grid_rowconfigure(3, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        # 响应摘要
        ttk.Label(left_frame, text="响应摘要:", font=self.subtitle_font).grid(row=0, column=0, sticky="w", pady=5)
        self.summary_text = scrolledtext.ScrolledText(left_frame, width=40, height=10, font=self.default_font)
        self.summary_text.grid(row=1, column=0, sticky="nsew", pady=20)
        left_frame.grid_rowconfigure(1, weight=1)

        # 数据拆分
        ttk.Label(left_frame, text="数据拆分:", font=self.subtitle_font).grid(row=2, column=0, sticky="w", pady=5)
        self.data_text = scrolledtext.ScrolledText(left_frame, width=40, height=10, font=self.default_font)
        self.data_text.grid(row=3, column=0, sticky="nsew", pady=20)
        left_frame.grid_rowconfigure(3, weight=1)

        # 校验结果
        ttk.Label(right_frame, text="校验结果:", font=self.subtitle_font).grid(row=0, column=0, sticky="w", pady=5)
        self.verify_text = scrolledtext.ScrolledText(right_frame, width=40, height=5, font=self.default_font)
        self.verify_text.grid(row=1, column=0, sticky="nsew", pady=20)
        right_frame.grid_rowconfigure(1, weight=1)

        # 原始响应
        ttk.Label(right_frame, text="原始响应:", font=self.subtitle_font).grid(row=2, column=0, sticky="w", pady=5)
        self.raw_text = scrolledtext.ScrolledText(right_frame, width=40, height=15, font=self.default_font)
        self.raw_text.grid(row=3, column=0, sticky="nsew", pady=20)
        right_frame.grid_rowconfigure(3, weight=1)

        # 返回按钮
        ttk.Button(frame, text="返回配置", command=lambda: self.tab_control.select(0), style="TButton").grid(row=1,
                                                                                                             column=0,
                                                                                                             columnspan=2,
                                                                                                             pady=10,
                                                                                                             sticky="s")

    def create_tutorial_tab(self):
        """教程页面"""
        frame = ttk.Frame(self.tab_tutorial, padding=20)
        frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)

        # 教程标题
        ttk.Label(frame, text="获取登录参数教程", font=self.subtitle_font).grid(row=0, column=0, columnspan=2,
                                                                                sticky="n", pady=15)

        # 左侧文本区域（可选中复制）
        left_frame = ttk.Frame(frame)
        left_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)

        tutorial_text = """
【第一步】打开登录页面
在浏览器地址栏中输入http://172.17.10.100/，打开网络登录页面。

【第二步】打开开发者工具
- Chrome/Firefox/Edge等现代浏览器中，按F12键或右键点击页面选择"检查"
- 切换到"Network"或"网络"面板

【第三步】捕获登录请求
- 在登录页面输入用户名和密码，但先不要点击登录
- 在开发者工具的Network面板中，点击"清空"按钮清除已有请求
- 点击登录按钮提交表单
- 在Network面板中，找到名称为"InterFace.do?method=login"的请求

【第四步】获取参数
- 点击选中"InterFace.do?method=login"请求
- 在右侧面板中，切换到"Headers"或"标头"选项卡
- 找到"Form Data"或"表单数据"部分
- 从中复制所需的参数：
  - userId：对应此处的"用户账号"
  - password：对应此处的"加密密码"
  - queryString：对应此处的"网络参数"
"""
        self.tutorial_display = scrolledtext.ScrolledText(left_frame,
                                                          width=40,
                                                          height=25,
                                                          font=self.default_font,
                                                          wrap=tk.WORD)
        self.tutorial_display.insert(tk.END, tutorial_text)
        self.tutorial_display.config(state=tk.DISABLED)  # 设为只读但可选择
        self.tutorial_display.pack(fill="both", expand=True)

        # 右侧图片区域（根据Pillow可用性显示）
        right_frame = ttk.Frame(frame)
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(10, 0))
        right_frame.grid_rowconfigure(0, weight=1)
        right_frame.grid_columnconfigure(0, weight=1)

        if PILLOW_AVAILABLE:
            # 图片显示区域
            image_frame = ttk.LabelFrame(right_frame, text="操作示意图", padding=5)
            image_frame.pack(fill="both", expand=True, pady=10)
            image_frame.grid_rowconfigure(0, weight=1)
            image_frame.grid_columnconfigure(0, weight=1)

            try:
                # 下载并显示图片 - 放大版本
                img_url = "https://img.picui.cn/free/2025/05/22/682f1e2cafbf2.png"
                img_data = requests.get(img_url, timeout=10).content
                img = Image.open(io.BytesIO(img_data))

                # 放大图片至合适尺寸，保持宽高比
                max_width = 600
                max_height = 400
                width, height = img.size
                aspect_ratio = width / height

                if width > max_width or height > max_height:
                    if aspect_ratio > 1:
                        new_width = max_width
                        new_height = int(new_width / aspect_ratio)
                    else:
                        new_height = max_height
                        new_width = int(new_height * aspect_ratio)
                    img = img.resize((new_width, new_height), Image.LANCZOS)

                self.tutorial_image = ImageTk.PhotoImage(img)
                ttk.Label(image_frame, image=self.tutorial_image).pack(pady=5, fill="both", expand=True)
            except Exception as e:
                self.logger.error(f"加载教程图片失败: {str(e)}")
                ttk.Label(image_frame, text=f"❌ 图片加载失败\n原因：{str(e)}", font=self.default_font).pack(pady=5)
        else:
            # 提示安装Pillow
            no_image_frame = ttk.LabelFrame(right_frame, text="图片显示", padding=5)
            no_image_frame.pack(fill="both", expand=True, pady=10)
            ttk.Label(no_image_frame, text="图片显示功能需要安装Pillow库", font=self.default_font).pack(pady=5)
            ttk.Label(no_image_frame, text="请在命令行运行:", font=self.default_font).pack(pady=2)
            ttk.Label(no_image_frame, text="pip install pillow", font=self.default_font).pack(pady=2)

        # 注意事项
        notes_frame = ttk.LabelFrame(right_frame, text="注意事项", padding=5)
        notes_frame.pack(fill="x", pady=10)
        notes_text = """
1. 请确保浏览器已更新到最新版本
2. 捕获请求时请不要关闭开发者工具
3. 参数可能包含特殊字符，请完整复制
4. 如有问题，请联系网络管理员
"""
        ttk.Label(notes_frame, text=notes_text, font=self.default_font, justify="left").pack(pady=5)

        # 返回按钮
        ttk.Button(frame, text="返回配置", command=lambda: self.tab_control.select(0), style="TButton").grid(row=2,
                                                                                                             column=0,
                                                                                                             columnspan=2,
                                                                                                             pady=15,
                                                                                                             sticky="s")

    def create_status_tab(self):
        """网络状态页面"""
        frame = ttk.Frame(self.tab_status, padding=20)
        frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        frame.grid_rowconfigure(4, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # 网络状态显示
        status_frame = ttk.LabelFrame(frame, text="网络监控状态", padding=10)
        status_frame.grid(row=0, column=0, sticky="nsew", pady=10)
        status_frame.grid_rowconfigure(0, weight=1)
        status_frame.grid_columnconfigure(0, weight=1)

        self.status_text = scrolledtext.ScrolledText(status_frame, width=70, height=10, font=self.default_font)
        self.status_text.pack(fill="both", expand=True, pady=10)
        self.status_text.config(state=tk.DISABLED)

        # 监控控制按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, sticky="ew", pady=10)

        self.monitor_btn = ttk.Button(btn_frame, text="开始监控", command=self.toggle_network_monitor, style="TButton")
        self.monitor_btn.pack(side="left", padx=5)

        self.test_ping_btn = ttk.Button(btn_frame, text="测试Ping", command=self.test_ping, style="TButton")
        self.test_ping_btn.pack(side="left", padx=5)

        # 监控间隔设置
        interval_frame = ttk.LabelFrame(frame, text="监控间隔设置", padding=10)
        interval_frame.grid(row=2, column=0, sticky="ew", pady=10)
        interval_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(interval_frame, text="Ping检查间隔 (秒):", font=self.default_font).pack(side="left", padx=5)
        self.interval_var = tk.StringVar(value=str(self.ping_interval))
        ttk.Entry(interval_frame, textvariable=self.interval_var, width=5, font=self.default_font).pack(side="left",
                                                                                                        padx=5)
        ttk.Button(interval_frame, text="应用设置", command=self.apply_interval, style="TButton").pack(side="left",
                                                                                                       padx=5)

        # 上次检查结果
        self.last_check_var = tk.StringVar(value="尚未进行检查")
        ttk.Label(frame, textvariable=self.last_check_var, font=self.subtitle_font).grid(row=3, column=0, sticky="n",
                                                                                         pady=10)

        # 可配置的检查网站列表
        sites_frame = ttk.Frame(frame)
        sites_frame.grid(row=4, column=0, sticky="ew", pady=10)
        sites_frame.grid_columnconfigure(0, weight=1)

        ttk.Label(sites_frame, text="当前检查站点:", font=self.default_font).pack(anchor="w", pady=5)
        self.sites_text = tk.Text(sites_frame, height=3, width=50, font=self.default_font)
        self.sites_text.insert(tk.END, "\n".join(self.check_sites))
        self.sites_text.pack(fill="x", pady=5)

        ttk.Button(sites_frame, text="应用站点设置", command=self.apply_sites, style="TButton").pack(anchor="w")

    def load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_file):
            try:
                self.logger.info("加载配置文件")
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        key, value = line.strip().split(' = ', 1)
                        self.config[key] = value.strip('"')
                self.logger.info(f"配置加载成功: {self.config.get('userAccount', '未知用户')}")

                # 加载配置到界面
                self.user_account.delete(0, tk.END)
                self.user_account.insert(0, self.config.get('userAccount', ''))

                self.encrypted_password.delete('1.0', tk.END)
                self.encrypted_password.insert(tk.END, self.config.get('encryptedPassword', ''))

                self.network_params.delete('1.0', tk.END)
                self.network_params.insert(tk.END, self.config.get('networkParams', ''))

                service_value = '%E4%B8%AD%E5%9B%BD%E7%A7%BB%E5%8A%A8%E5%AE%BD%E5%B8%A6'
                self.service_name.set('cmcc' if self.config.get('serviceName') == service_value else 'telecom')

                return True
            except Exception as e:
                self.logger.error(f"加载配置失败: {str(e)}")
                messagebox.showerror("错误", f"加载配置失败：{str(e)}")
                return False
        self.logger.info("未找到配置文件")
        return False

    def load_auto_start_status(self):
        """加载自启动状态"""
        if sys.platform.startswith('win'):
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                     "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                                     0, winreg.KEY_READ)
                # 安全获取注册表值，避免元组解包错误
                result = winreg.QueryValueEx(key, self.auto_start_key)
                if len(result) >= 2:  # 确保返回值至少包含两个元素
                    value = result[0]
                    self.auto_start = (value == self.auto_start_path)
                else:
                    self.auto_start = False
                winreg.CloseKey(key)
            except (FileNotFoundError, WindowsError, ValueError):
                self.auto_start = False
        elif sys.platform == 'darwin':
            self.auto_start = os.path.exists(os.path.expanduser(f"~/Library/LaunchAgents/{self.auto_start_key}.plist"))
        elif sys.platform.startswith('linux'):
            self.auto_start = os.path.exists(os.path.expanduser(f"~/.config/autostart/{self.auto_start_key}.desktop"))

    def toggle_auto_start(self):
        """切换自启动状态"""
        if self.auto_start_var.get():
            self.enable_auto_start()
        else:
            self.disable_auto_start()

    def enable_auto_start(self):
        """启用自启动"""
        try:
            self.logger.info("启用自启动功能")
            if sys.platform.startswith('win'):
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Run", 0,
                                     winreg.KEY_WRITE)
                winreg.SetValueEx(key, self.auto_start_key, 0, winreg.REG_SZ, self.auto_start_path)
                winreg.CloseKey(key)
            elif sys.platform == 'darwin':
                plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{self.auto_start_key}.plist")
                plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{self.auto_start_key}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{self.auto_start_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""
                with open(plist_path, 'w') as f:
                    f.write(plist_content)
                subprocess.run(["launchctl", "load", plist_path])
            elif sys.platform.startswith('linux'):
                desktop_path = os.path.expanduser(f"~/.config/autostart/{self.auto_start_key}.desktop")
                desktop_content = f"""[Desktop Entry]
Type=Application
Name={self.auto_start_key}
Exec={self.auto_start_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=校园网自动登录工具"""
                os.makedirs(os.path.dirname(desktop_path), exist_ok=True)
                with open(desktop_path, 'w') as f:
                    f.write(desktop_content)
                # 设置文件权限
                os.chmod(desktop_path, 0o644)
            self.auto_start = True
            self.logger.info("自启动已启用")
            messagebox.showinfo("提示", "自启动已启用")
        except Exception as e:
            self.logger.error(f"启用自启动失败: {str(e)}")
            messagebox.showerror("错误", f"启用自启动失败：{str(e)}")
            self.auto_start_var.set(0)  # 取消勾选

    def disable_auto_start(self):
        """禁用自启动"""
        try:
            self.logger.info("禁用自启动功能")
            if sys.platform.startswith('win'):
                try:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
                                         0, winreg.KEY_WRITE)
                    winreg.DeleteValue(key, self.auto_start_key)
                    winreg.CloseKey(key)
                except WindowsError:
                    pass  # 键不存在时忽略
            elif sys.platform == 'darwin':
                plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{self.auto_start_key}.plist")
                if os.path.exists(plist_path):
                    subprocess.run(["launchctl", "unload", plist_path])
                    os.remove(plist_path)
            elif sys.platform.startswith('linux'):
                desktop_path = os.path.expanduser(f"~/.config/autostart/{self.auto_start_key}.desktop")
                if os.path.exists(desktop_path):
                    os.remove(desktop_path)
            self.auto_start = False
            self.logger.info("自启动已禁用")
            messagebox.showinfo("提示", "自启动已禁用")
        except Exception as e:
            self.logger.error(f"禁用自启动失败: {str(e)}")
            messagebox.showerror("错误", f"禁用自启动失败：{str(e)}")
            self.auto_start_var.set(1)  # 重新勾选

    def auto_login(self):
        """自动登录功能"""
        # 检查必要配置
        required_fields = ['userAccount', 'encryptedPassword', 'serviceName', 'networkParams', 'targetUrl']
        if not all(field in self.config for field in required_fields):
            self.logger.warning("配置不完整，无法自动登录")
            messagebox.showwarning("提示", "配置不完整，无法自动登录")
            return

        # 清空结果区域
        for widget in (self.summary_text, self.data_text, self.verify_text, self.raw_text):
            widget.delete('1.0', tk.END)

        # 显示登录信息
        self.summary_text.insert(tk.END, "检测到配置文件，准备自动登录...\n")
        self.summary_text.insert(tk.END, f"用户账号: {self.config['userAccount']}\n")
        self.summary_text.insert(tk.END, f"服务提供商: {self.config['serviceName']}\n")
        self.summary_text.insert(tk.END, "正在检查网络连接状态...\n")
        self.root.update()

        # 在单独线程中检查网络连接
        threading.Thread(target=self.check_network_before_login, daemon=True).start()

    def check_network_before_login(self):
        """在登录前检查网络连接状态"""
        self.initial_network_check_attempts = 0

        while self.initial_network_check_attempts < self.max_initial_check_attempts:
            self.initial_network_check_attempts += 1

            self.update_status(
                f"🔍 检查网络连接 ({self.initial_network_check_attempts}/{self.max_initial_check_attempts})...")
            self.logger.info(f"检查网络连接 ({self.initial_network_check_attempts}/{self.max_initial_check_attempts})")

            # 检查网络连接
            if self.is_network_connected():
                self.update_status("✅ 网络已连接，准备登录...")
                self.logger.info("网络已连接，准备登录")

                # 在主线程执行登录
                if self.root_active:  # 新增：检查窗口是否已销毁
                    self.root.after(0, self.login)
                return
            else:
                wait_time = self.initial_check_delay * self.initial_network_check_attempts
                self.update_status(f"❌ 网络未连接，等待 {wait_time} 秒后重试...")
                self.logger.warning(f"网络未连接，等待 {wait_time} 秒后重试")

                # 指数退避算法：每次等待时间递增
                time.sleep(wait_time)

        # 达到最大尝试次数
        self.update_status(f"❗ 尝试 {self.max_initial_check_attempts} 次后仍无法连接网络，登录失败")
        self.logger.error(f"尝试 {self.max_initial_check_attempts} 次后仍无法连接网络")
        self.last_check_var.set("网络状态: 未连接")
        if self.root_active:  # 新增：检查窗口是否已销毁
            self.root.after(0, lambda: messagebox.showerror("登录失败", "尝试多次后仍无法连接网络，请检查网络设置"))

    def is_network_connected(self):
        """检查网络是否连接"""
        try:
            # 尝试连接到本地网关或DNS服务器
            # 使用较短的超时时间以快速检测
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            return True
        except OSError:
            return False

    def save_config(self):
        """保存配置文件"""
        try:
            service_name = '%E4%B8%AD%E5%9B%BD%E7%A7%BB%E5%8A%A8%E5%AE%BD%E5%B8%A6' if self.service_name.get() == 'cmcc' else '%E4%B8%AD%E5%9B%BD%E7%94%B5%E4%BF%A1%E5%AE%BD%E5%B8%A6'
            self.config = {
                'userAccount': self.user_account.get(),
                'encryptedPassword': self.encrypted_password.get('1.0', tk.END).strip(),
                'serviceName': service_name,
                'targetUrl': 'http://172.17.10.100/eportal/InterFace.do?method=login',
                'networkParams': self.network_params.get('1.0', tk.END).strip()
            }

            # 验证必要字段
            if not self.config['userAccount'] or not self.config['encryptedPassword'] or not self.config[
                'networkParams']:
                self.logger.warning("保存配置失败：必要字段为空")
                messagebox.showerror("错误", "用户账号、加密密码和网络参数不能为空")
                return False

            with open(self.config_file, 'w', encoding='utf-8') as f:
                for key, value in self.config.items():
                    f.write(f'{key} = "{value}"\n')
            self.logger.info(f"配置保存成功: {self.config['userAccount']}")
            return True
        except Exception as e:
            self.logger.error(f"保存配置失败: {str(e)}")
            messagebox.showerror("错误", f"保存配置失败：{str(e)}")
            return False

    def reset_config(self):
        """重置配置"""
        if os.path.exists(self.config_file):
            os.remove(self.config_file)
            self.logger.info("配置文件已删除")
        self.user_account.delete(0, tk.END)
        self.encrypted_password.delete('1.0', tk.END)
        self.network_params.delete('1.0', tk.END)
        messagebox.showinfo("提示", "配置已重置")

    def login(self):
        """执行登录"""
        try:
            # 构造参数
            post_params = {
                'userId': self.config['userAccount'],
                'password': self.config['encryptedPassword'],
                'service': self.config['serviceName'],
                'queryString': self.config['networkParams'],
                'operatorPwd': '',
                'operatorUserId': '',
                'validcode': '',
                'passwordEncrypt': 'true'
            }
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36'
            }

            # 发送请求
            self.summary_text.insert(tk.END, "正在发送登录请求...\n")
            if self.root_active:  # 新增：检查窗口是否已销毁
                self.root.update()
            self.logger.info(f"发送登录请求: {self.config['userAccount']}")
            response = requests.post(self.config['targetUrl'], data=post_params, headers=headers, timeout=30)

            # 处理响应
            self.summary_text.insert(tk.END, f"HTTP状态码：{response.status_code}\n")
            self.summary_text.insert(tk.END, f"响应长度：{len(response.text)} 字节\n")
            self.logger.info(f"登录响应: 状态码 {response.status_code}, 长度 {len(response.text)}")

            try:
                json_data = response.json()
                self.raw_text.insert(tk.END, json.dumps(json_data, indent=2))
            except json.JSONDecodeError:
                self.summary_text.insert(tk.END, "\n❌ 响应非JSON格式\n")
                self.raw_text.insert(tk.END, response.text)
                self.logger.error("登录响应不是有效的JSON格式")
                return

            # 解析userIndex
            if 'userIndex' not in json_data:
                self.summary_text.insert(tk.END, "\n❌ 响应中缺少userIndex字段\n")
                self.logger.error("登录响应中缺少userIndex字段")
                return

            hex_user_index = json_data['userIndex']
            try:
                decoded = binascii.unhexlify(hex_user_index).decode('utf-8', errors='replace')
                self.summary_text.insert(tk.END, f"\n原始十六进制：{hex_user_index}\n解码内容：{decoded}\n")
                self.logger.info(f"userIndex解码成功: {decoded}")
            except binascii.Error:
                self.summary_text.insert(tk.END, f"\n❌ userIndex格式错误：{hex_user_index}\n")
                self.logger.error(f"userIndex格式错误: {hex_user_index}")
                return

            # 拆分数据
            segments = decoded.split('_')
            if len(segments) >= 3:
                self.data_text.insert(tk.END, f"设备标识：{segments[0]}\n分配IP：{segments[1]}\n用户账号：{segments[2]}\n")
                self.verify_text.insert(tk.END,
                                        f"账号一致性：{'✔️ 一致' if segments[2] == self.config['userAccount'] else '❌ 不一致'}\n")
                self.logger.info(f"登录成功: {segments[2]}")
                self.last_check_var.set("网络状态: 已连接")
            else:
                self.data_text.insert(tk.END, "❌ 数据格式异常，无法拆分\n")
                self.logger.warning("登录响应数据格式异常")
                self.last_check_var.set("网络状态: 连接失败")

            if self.root_active:  # 新增：检查窗口是否已销毁
                self.tab_control.select(1)

        except Exception as e:
            error_msg = f"登录失败: {str(e)}"
            self.logger.error(error_msg)
            if self.root_active:  # 新增：检查窗口是否已销毁
                messagebox.showerror("登录失败", error_msg)
                self.summary_text.insert(tk.END, f"\n错误详情：{str(e)}\n")
                self.last_check_var.set("网络状态: 连接失败")

    def save_config_and_login(self):
        """保存配置并登录"""
        if self.save_config():
            self.login()

    def start_network_monitor(self):
        """启动网络监控线程"""
        if self.monitoring:
            return

        self.monitoring = True
        self.monitor_btn.config(text="停止监控")
        self.logger.info(f"启动网络监控，间隔 {self.ping_interval} 秒")

        self.monitor_thread = threading.Thread(target=self.network_monitor_loop, daemon=True)
        self.monitor_thread.start()

        self.update_status("✅ 网络监控已启动")

    def stop_network_monitor(self):
        """停止网络监控线程"""
        self.monitoring = False
        self.monitor_btn.config(text="开始监控")
        self.logger.info("停止网络监控")
        self.update_status("🛑 网络监控已停止")

    def toggle_network_monitor(self):
        """切换网络监控状态"""
        if self.monitoring:
            self.stop_network_monitor()
        else:
            self.start_network_monitor()

    def network_monitor_loop(self):
        """网络监控主循环"""
        while self.monitoring:
            try:
                self.check_network_status()
                time.sleep(self.ping_interval)
            except Exception as e:
                self.logger.error(f"网络监控出错: {str(e)}")
                time.sleep(self.ping_interval)

    def check_network_status(self):
        """检查网络状态"""
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.update_status(f"🔍 [{current_time}] 正在检查网络连接...")

        connected = False
        for site in self.check_sites:
            try:
                socket.create_connection((site, 80), timeout=5)
                self.update_status(f"✅ [{current_time}] 连接 {site} 成功")
                connected = True
                break
            except OSError:
                self.update_status(f"❌ [{current_time}] 连接 {site} 失败")

        if connected:
            status = "网络状态: 已连接"
            self.update_status(f"✅ [{current_time}] 网络连接正常")
        else:
            status = "网络状态: 未连接"
            self.update_status(f"❗ [{current_time}] 网络连接断开，尝试重新登录...")
            self.logger.warning("网络连接断开，尝试重新登录")
            if self.root_active:  # 新增：检查窗口是否已销毁
                self.root.after(0, self.login)  # 在主线程执行登录

        self.last_check_var.set(status)

    def test_ping(self):
        """测试Ping功能"""
        threading.Thread(target=self._test_ping_thread, daemon=True).start()

    def _test_ping_thread(self):
        """Ping测试线程"""
        self.update_status("🔍 开始Ping测试...")
        results = []

        for site in self.check_sites:
            try:
                start_time = time.time()
                socket.create_connection((site, 80), timeout=5)
                end_time = time.time()
                latency = (end_time - start_time) * 1000  # 转换为毫秒
                results.append(f"✅ {site}: {latency:.2f}ms")
                self.update_status(f"✅ {site}: {latency:.2f}ms")
            except OSError as e:
                results.append(f"❌ {site}: 连接失败 ({str(e)})")
                self.update_status(f"❌ {site}: 连接失败 ({str(e)})")

        result_text = "\n".join(results)
        self.logger.info(f"Ping测试结果:\n{result_text}")

    def update_status(self, message):
        """更新状态文本"""
        if not self.root_active:  # 新增：检查窗口是否已销毁
            return

        self.root.after(0, lambda: self._update_status_ui(message))

    def _update_status_ui(self, message):
        """在UI线程中更新状态文本"""
        self.status_text.config(state=tk.NORMAL)
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)

    def apply_interval(self):
        """应用监控间隔设置"""
        try:
            new_interval = int(self.interval_var.get())
            if new_interval < 10:
                messagebox.showerror("错误", "监控间隔不能小于10秒")
                return
            self.ping_interval = new_interval
            self.logger.info(f"更新监控间隔为 {self.ping_interval} 秒")
            messagebox.showinfo("提示", f"监控间隔已更新为 {self.ping_interval} 秒")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的整数")

    def apply_sites(self):
        """应用检查网站设置"""
        sites_text = self.sites_text.get("1.0", tk.END).strip()
        sites = [site.strip() for site in sites_text.split("\n") if site.strip()]

        if not sites:
            messagebox.showerror("错误", "检查站点列表不能为空")
            return

        self.check_sites = sites
        self.logger.info(f"更新检查站点列表: {', '.join(self.check_sites)}")
        messagebox.showinfo("提示", "检查站点列表已更新")


if __name__ == "__main__":
    root = tk.Tk()
    app = NetworkLoginApp(root)
    root.mainloop()