import wx
import os
# import sys
# # 将项目的根目录添加到 sys.path 中
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from model.plot.PointCloudCanvas import PointCloudCanvas


# 颜色常量定义
BG_COLOR_LIGHT_GREEN = wx.Colour(240, 250, 250)  # 浅绿色背景
BG_COLOR_WHITE = wx.WHITE
BG_COLOR_GREEN = wx.Colour(107, 175, 107)  # 绿色（开始按钮）
BG_COLOR_RED = wx.Colour(244, 100, 80)  # 红色（结束按钮）
BG_COLOR_BLUE = wx.Colour(150, 230, 244)  # 钻石蓝（参数按钮）


class BorderedPanel(wx.Panel):
    """带明显黑色边框的面板"""

    def __init__(self, parent, label="", bg_color=None):
        super().__init__(parent)
        self.label = label
        self.bg_color = bg_color or wx.Colour(220, 247, 221)
        self.SetBackgroundColour(self.bg_color)
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def _on_paint(self, event):
        """绘制黑色边框"""
        dc = wx.PaintDC(self)
        rect = self.GetClientRect()

        # 绘制背景
        dc.SetBrush(wx.Brush(self.bg_color))
        dc.DrawRectangle(rect)

        # 绘制粗黑色边框（3像素）
        dc.SetPen(wx.Pen(wx.BLACK, 3))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(0, 0, rect.width, rect.height)

        # 绘制标签（如果有）
        if self.label:
            font = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)  # 改为普通字体，不加粗
            dc.SetFont(font)
            dc.SetTextForeground(wx.BLACK)
            text_width, text_height = dc.GetTextExtent(self.label)

            # 标签位置：顶部左侧，内缩一点，向下间隔10像素
            label_x = 15
            label_y = 15

            # 在标签周围地方画白色背景来遮挡边框
            bg_margin = 3  # 标签周围的白色边距
            dc.SetBrush(wx.Brush(self.bg_color))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(label_x - bg_margin, label_y - bg_margin, text_width + 2 * bg_margin, text_height + 2 * bg_margin)

            # 绘制标签文字
            dc.DrawText(self.label, label_x, label_y)


class ModernButton(wx.Button):
    """现代化按钮类 - 所有按钮显示darker效果和边框"""

    def __init__(self, parent, label, size=wx.Size(150, 50), bg_color=None, text_color=None):
        super().__init__(parent, label=label, size=size)
        self.bg_color = bg_color or BG_COLOR_BLUE  # 原始背景色
        self.text_color = text_color or wx.BLACK  # 文字颜色
        self.disabled_color = wx.Colour(180, 180, 180)  # 禁用时的灰色
        self.visual_active = True
        self.current_text_color = self.text_color

        # 使用普通字体（不加粗）来避免文字重叠
        font = wx.Font(13, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self.SetFont(font)

        # 绑定Paint事件
        self.Bind(wx.EVT_PAINT, self._on_paint)

        # 初始化颜色
        self._update_button_appearance()

    def _update_button_appearance(self):
        """根据启用/禁用状态更新按钮外观"""
        if self.IsEnabled() and self.visual_active:
            # 启用时：使用darker效果（减20）
            self.current_bg = wx.Colour(max(0, self.bg_color.red - 20), max(0, self.bg_color.green - 20), max(0, self.bg_color.blue - 20))
            self.current_text_color = self.text_color
        else:
            # 禁用时：使用灰色
            self.current_bg = self.disabled_color
            self.current_text_color = wx.BLACK

        self.SetBackgroundColour(self.current_bg)
        self.SetForegroundColour(self.current_text_color)

    def SetVisualActive(self, active=True):
        """仅控制按钮是否显示彩色外观，不影响点击能力"""
        self.visual_active = active
        self._update_button_appearance()
        self.Refresh()

    def Enable(self, enable=True):
        """重写Enable方法以更新按钮外观"""
        super().Enable(enable)
        self._update_button_appearance()
        self.Refresh()

    def _on_paint(self, event):
        """自定义绘制 - 显示darker效果和边框"""
        dc = wx.PaintDC(self)
        rect = self.GetClientRect()

        # 绘制主背景
        dc.SetBrush(wx.Brush(self.current_bg))
        dc.SetPen(wx.Pen(self.current_bg))
        dc.DrawRectangle(rect)

        # 绘制深色边框（3像素）给按钮凹陷感
        border_color = wx.Colour(max(0, self.current_bg.red - 30), max(0, self.current_bg.green - 30), max(0, self.current_bg.blue - 30))
        dc.SetPen(wx.Pen(border_color, 2))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(0, 0, rect.width - 1, rect.height - 1)

        # 获取文字
        label = self.GetLabel()
        font = self.GetFont()
        dc.SetFont(font)

        # 测量文字尺寸
        text_width, text_height = dc.GetTextExtent(label)
        x = (rect.width - text_width) // 2
        y = (rect.height - text_height) // 2

        # 绘制文字
        dc.SetTextForeground(self.current_text_color)
        dc.DrawText(label, x, y)


class MainFrame(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent, title="Joihey Software")
        self.SetBackgroundColour(BG_COLOR_LIGHT_GREEN)

        # 尝试加载ico图标（如果存在）
        icon_path = os.path.join(os.path.dirname(__file__), "..", "data", "picture", "junhe.ico")
        if os.path.exists(icon_path):
            icon = wx.Icon(icon_path, wx.BITMAP_TYPE_ICO)
            self.SetIcon(icon)

        self.InitUI()
        # 设置窗口为最大化状态（自适应屏幕尺寸）
        self.Maximize(True)
        self._set_control_buttons_active(False)
        self._set_param_buttons_enabled(False)

    def InitUI(self):
        # 创建滚动窗口
        scrolled_window = wx.ScrolledWindow(self)
        scrolled_window.SetScrollRate(20, 20)
        scrolled_window.SetBackgroundColour(BG_COLOR_LIGHT_GREEN)

        # 主面板
        panel = wx.Panel(scrolled_window)
        panel.SetBackgroundColour(BG_COLOR_LIGHT_GREEN)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # ================= Left: Control Panel =================
        left_scrolled = wx.ScrolledWindow(panel, size=wx.Size(410, -1))
        left_scrolled.SetScrollRate(10, 10)
        left_scrolled.SetBackgroundColour(wx.Colour(240, 240, 240))
        left_scrolled.SetMinSize(wx.Size(410, -1))

        left_vbox = wx.BoxSizer(wx.VERTICAL)

        # Control box
        control_box = wx.StaticBox(left_scrolled, label="Control Panel")
        control_box_sizer = wx.StaticBoxSizer(control_box, wx.VERTICAL)

        btn_sizer1 = wx.BoxSizer(wx.HORIZONTAL)
        self.start_btn = ModernButton(control_box_sizer.GetStaticBox(), label="Start Software", size=wx.Size(180, 40), bg_color=BG_COLOR_GREEN)
        self.stop_btn = ModernButton(control_box_sizer.GetStaticBox(), label="Stop Software", size=wx.Size(180, 40), bg_color=BG_COLOR_RED)
        btn_sizer1.Add(self.start_btn, 0, wx.ALL, 5)
        btn_sizer1.Add(self.stop_btn, 0, wx.ALL, 5)

        status_sizer1 = wx.BoxSizer(wx.HORIZONTAL)
        status_label1 = wx.StaticText(control_box_sizer.GetStaticBox(), label="Lidar Scan Position:", size=wx.Size(140, 30))
        self.chain_pos_text = wx.TextCtrl(control_box_sizer.GetStaticBox(), value="0", size=wx.Size(100, 30))
        status_label2 = wx.StaticText(control_box_sizer.GetStaticBox(), label="mm", size=wx.Size(50, 30))
        self.chain_pos_text.Enable(False)
        status_sizer1.Add(status_label1, 0, wx.ALL, 5)
        status_sizer1.Add(self.chain_pos_text, 0, wx.ALL, 5)
        status_sizer1.Add(status_label2, 0, wx.ALL, 5)

        control_box_sizer.Add(btn_sizer1, 0, wx.ALL, 5)
        control_box_sizer.Add(status_sizer1, 0, wx.ALL, 5)

        # Parameter box
        param_box = wx.StaticBox(left_scrolled, label="Parameter Settings")
        param_box_sizer = wx.StaticBoxSizer(param_box, wx.VERTICAL)

        status_sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        status_label3 = wx.StaticText(param_box_sizer.GetStaticBox(), label="Lidar Scan Speed:", size=wx.Size(140, 30))
        self.chain_speed_text = wx.TextCtrl(param_box_sizer.GetStaticBox(), value="25", size=wx.Size(100, 30))
        status_label4 = wx.StaticText(param_box_sizer.GetStaticBox(), label="mm/s", size=wx.Size(50, 30))
        status_sizer2.Add(status_label3, 0, wx.ALL, 5)
        status_sizer2.Add(self.chain_speed_text, 0, wx.ALL, 5)
        self.chain_speed_text.Enable(False)
        status_sizer2.Add(status_label4, 0, wx.ALL, 5)

        param_box_sizer.Add(status_sizer2, 0, wx.EXPAND | wx.ALL, 5)
        self.save_setting_btn = ModernButton(param_box_sizer.GetStaticBox(), label="Save setting", size=wx.Size(180, 40), bg_color=BG_COLOR_BLUE)
        param_box_sizer.Add(self.save_setting_btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)

        # Spray box
        spray_box = wx.StaticBox(left_scrolled, label="Spraying Control")
        spray_box_sizer = wx.StaticBoxSizer(spray_box, wx.VERTICAL)

        status_label10 = wx.StaticText(spray_box_sizer.GetStaticBox(), label="                    Left                                         Right", size=wx.Size(300, 30))
        btn_sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        self.left_side_btn = ModernButton(spray_box_sizer.GetStaticBox(), label="Side Spray Machine", size=wx.Size(180, 40), bg_color=BG_COLOR_BLUE)
        self.right_side_btn = ModernButton(spray_box_sizer.GetStaticBox(), label="Side Spray Machine", size=wx.Size(180, 40), bg_color=BG_COLOR_BLUE)
        btn_sizer2.Add(self.left_side_btn, 0, wx.ALL, 5)
        btn_sizer2.Add(self.right_side_btn, 0, wx.ALL, 5)

        btn_sizer3 = wx.BoxSizer(wx.HORIZONTAL)
        self.left_lift_btn = ModernButton(spray_box_sizer.GetStaticBox(), label="2D Lift Machine", size=wx.Size(180, 40), bg_color=BG_COLOR_BLUE)
        self.right_lift_btn = ModernButton(spray_box_sizer.GetStaticBox(), label="2D Lift Machine", size=wx.Size(180, 40), bg_color=BG_COLOR_BLUE)
        btn_sizer3.Add(self.left_lift_btn, 0, wx.ALL, 5)
        btn_sizer3.Add(self.right_lift_btn, 0, wx.ALL, 5)

        spray_box_sizer.Add(status_label10, 0, wx.EXPAND | wx.ALL, 5)
        spray_box_sizer.Add(btn_sizer2, 0, wx.EXPAND | wx.ALL, 5)
        spray_box_sizer.Add(btn_sizer3, 0, wx.EXPAND | wx.ALL, 5)

        # Status output panel (moved to right)
        status_panel = wx.Panel(panel)
        status_panel.SetBackgroundColour(wx.Colour(240, 240, 240))
        status_panel.SetMinSize(wx.Size(300, 300))
        status_sizer = wx.BoxSizer(wx.VERTICAL)
        status_label = wx.StaticText(status_panel, label="Status Output:")
        self.status_text = wx.TextCtrl(status_panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.status_text.SetInsertionPointEnd()

        status_sizer.Add(status_label, 0, wx.ALL, 5)
        status_sizer.Add(self.status_text, 1, wx.EXPAND | wx.ALL, 5)
        status_panel.SetSizer(status_sizer)

        left_vbox.Add(control_box_sizer, 0, wx.EXPAND | wx.ALL, 10)
        left_vbox.Add(param_box_sizer, 0, wx.EXPAND | wx.ALL, 10)
        left_vbox.Add(spray_box_sizer, 0, wx.EXPAND | wx.ALL, 10)

        left_scrolled.SetSizer(left_vbox)

        # ================= Center: 3D View =================
        right_panel = wx.Panel(panel)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        center_panel = wx.Panel(right_panel)
        center_panel.SetBackgroundColour(wx.Colour(200, 200, 200))
        center_panel.SetMinSize(wx.Size(300, 200))
        center_sizer = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(center_panel, label="3D Point Cloud Visualization")
        center_sizer.Add(title_label, 0, wx.ALIGN_CENTER | wx.TOP, 10)

        self.gl_canvas = PointCloudCanvas(center_panel)
        center_sizer.Add(self.gl_canvas, 1, wx.EXPAND | wx.ALL, 5)
        center_panel.SetSizer(center_sizer)

        right_sizer.Add(center_panel, 1, wx.EXPAND | wx.ALL, 5)
        right_panel.SetSizer(right_sizer)

        # ================= Main layout =================
        main_sizer.Add(left_scrolled, 0, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(right_panel, 1, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(status_panel, 0, wx.EXPAND | wx.ALL, 5)

        panel.SetSizer(main_sizer)

        scrolled_sizer = wx.BoxSizer(wx.VERTICAL)
        scrolled_sizer.Add(panel, 1, wx.EXPAND)
        scrolled_window.SetSizer(scrolled_sizer)

        # 设置字体
        default_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        self.SetFont(default_font)

        # 设置虚拟大小
        left_scrolled.SetVirtualSize(left_vbox.GetMinSize())

    def _set_param_buttons_enabled(self, enabled: bool):
        """设置参数设置按钮的启用/禁用状态"""
        self.left_side_btn.Enable(enabled)
        self.right_side_btn.Enable(enabled)
        self.left_lift_btn.Enable(enabled)
        self.right_lift_btn.Enable(enabled)

    def _set_control_buttons_active(self, active: bool):
        """设置开始/结束按钮是否显示彩色外观"""
        self.start_btn.SetVisualActive(active)
        self.stop_btn.SetVisualActive(active)
        self.save_setting_btn.SetVisualActive(active)
        self.start_btn.Enable(True)
        self.stop_btn.Enable(active)

    def on_program_started(self):
        """程序启动后被调用，启用彩色按钮和参数设置按钮"""
        self._set_control_buttons_active(True)
        self._set_param_buttons_enabled(True)

    def on_program_stopped(self):
        """程序停止后被调用，恢复为灰色按钮并禁用参数设置按钮"""
        self._set_control_buttons_active(False)
        self._set_param_buttons_enabled(False)


if __name__ == "__main__":
    app = wx.App()
    frame = MainFrame(None)
    frame.Show()
    app.MainLoop()
