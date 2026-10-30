from pathlib import Path
import ast, math, json
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'Y分枪逻辑图'; OUT.mkdir(exist_ok=True)
F='C:/Windows/Fonts/msyh.ttc'
BLUE='#1761a0'; TEAL='#007d78'; GRAY='#67717b'; LIGHT='#d8e0e7'; ORANGE='#a85b00'
def text(d,x,y,s,n=30):d.text((x,y),s,font=ImageFont.truetype(F,n),fill='black')
def line(d,points,c=BLUE,w=5,tip=True):
    d.line(points,fill=c,width=w)
    if tip:
        (a,b),(x,y)=points[-2:]; angle=math.atan2(y-b,x-a)
        d.polygon([(x,y),(x-17*math.cos(angle-.45),y-17*math.sin(angle-.45)),(x-17*math.cos(angle+.45),y-17*math.sin(angle+.45))],fill=c)
def box(d,x,y,w,h,title,body,accent=BLUE):
    d.rounded_rectangle((x,y,x+w,y+h),radius=14,fill='white',outline=accent,width=3)
    d.rectangle((x+2,y+20,x+8,y+h-20),fill=accent)
    text(d,x+25,y+18,title,32)
    for i,s in enumerate(body):text(d,x+25,y+72+i*43,s,26)
def canvas(title,sub):
    im=Image.new('RGB',(2560,1440),'white');d=ImageDraw.Draw(im)
    text(d,65,35,title,49);text(d,65,110,sub,27)
    d.line((65,163,2495,163),fill=LIGHT,width=2)
    return im,d
def save(im,name):im.save(OUT/name,dpi=(200,200))

im,d=canvas('xn_side  /  完整分枪后的自动规划流程','柜体主流程｜当前配置：独立 Y、二维同时往复、X 轴计次、R 旋转开启、内腔背板喷涂关闭')
w=545;h=215;xs=[65,695,1325,1955];ys=[215,545,875]
nodes=[
 ('01 读取当前设备分枪结果',['按设备 SN 找到枪组','外侧组 + 每列内侧组','读取使能、Y 下限、Y 上限']),
 ('02 自动条件与队列检查',['自动使能、伺服及激光状态','无工件：安全归位并等待','Z 限位保护另行上报停链']),
 ('03 等待柜体前外侧到达',['Z 先到柜体模式安全目标','X 到外侧等待位；Y 到下限','R = −90°，按位置触发']),
 ('04 前外侧往复喷涂',['使用外侧分枪组','X / Y 同时往复，Z 跟链','完成 outside_total_cycles']),
 ('05 收枪并查找可进入列',['仅 X 收到外侧等待位','Y / R 保持，Z 跟随或返回','有可进入列 → 内侧流程']),
 ('06 等待本列前内侧',['切换本列的 inside 分枪组','R = +90°，按位置等待','已错过该列：检查下一列']),
 ('07 本列前内侧往复',['使用本列启用枪及 Y 范围','X / Y 同时往复，Z 跟链','完成 inside_total_cycles']),
 ('08 收枪并等待后内侧',['当前配置跳过内腔背板喷涂','X 收枪时 Y / R 保持','等待阶段 R = −90°']),
 ('09 本列后内侧往复',['使用本列 inside 分枪组','X / Y 同时往复，Z 跟链','完成 inside_total_cycles']),
 ('10 收枪并检查下一列',['有下一可进入列：回到 06','无下一列：进入后外侧','无可进入列时也走后外侧']),
 ('11 等待并喷涂后外侧',['等待阶段及喷涂 R = +90°','切回 outside 分枪组','完成 outside_total_cycles']),
 ('12 安全归位与完成',['先 X 回安全位，再退 Y / R','X 未回位时 Z 按安全策略跟随','全部到位后移除该设备队首工件'])]
positions=[]
for i,(t,b) in enumerate(nodes):
    row=i//4;col=i%4 if row%2==0 else 3-i%4
    x,y=xs[col],ys[row];positions.append((x,y))
    box(d,x,y,w,h,t,b,TEAL if i in (3,6,8,10) else BLUE)
for i in range(11):
    x,y=positions[i];nx,ny=positions[i+1]
    if y==ny:
        a=x+w if nx>x else x;b=nx if nx>x else nx+w
        line(d,[(a,y+h/2),(b,ny+h/2)])
    else:line(d,[(x+w/2,y+h),(nx+w/2,ny)])
# Explicit loop routed in the gap above the bottom row.
line(d,[(695+272,875),(967,820),(1597,820),(1597,760)],TEAL,4)
text(d,1030,781,'下一列 → 回到 06',25)
text(d,65,1145,'主线触发：链条位置与工件边界比较；往复段触发：PLC 实际轴位置到位 + 配置循环次数。',29)
text(d,65,1200,'分枪只提供“哪些枪参与、Y 在哪里运动”；X 范围、R 角度、Z 跟随和换面顺序由运动规划逐周期计算。',28)
text(d,65,1260,'适用范围：本图为柜体正常分支；错过工件、无启用枪、背板开关等分支见图 3。',27)
text(d,65,1330,'代码核查提示：当前内腔准入函数存在未定义变量；本图表达状态转移设计，不能作为已通过实机验证的说明。',25)
save(im,'xn_side_01_自动规划总流程_白底.png')

im,d=canvas('xn_side  /  分枪结果如何变成各轴路径','当前二维模式：X 与 Y 同时往复；依据 PLC 到位反馈逐步换向，不预先生成固定斜线或固定蛇形轨迹')
box(d,65,205,760,230,'① 从分枪和柜体边界生成运动范围',[
 'Y：读取下限 / 上限，执行限位及行程缩减',
 'X：工件 X 边界 − 前后偏移 − 安装位置',
 'R：按喷涂面切换；Z：按阶段跟链或回退'])
box(d,900,205,750,230,'② 定位后启动二维往复',[
 '独立 Y：各枪先到自己的下限',
 '启用枪 X 到 Xmin 后统一进入往复',
 'X、各 Y 分别依据反馈到位后换向'])
box(d,1725,205,770,230,'③ 按配置计次并结束该喷涂面',[
 '当前按 X：Xmin → Xmax → Xmin 算一轮',
 '外侧 / 内侧使用各自配置的循环次数',
 '达到次数后结束本面，进入收枪或换面'])
line(d,[(825,320),(900,320)]);line(d,[(1650,320),(1725,320)])
text(d,85,490,'共享 Y：一根公共 Y 轴',37)
text(d,85,552,'公共范围 = 启用枪区间交集，再减去往复缩减量',27)
text(d,85,598,'示意：所有启用枪随同一个 Y 行程运动',27)
for i,x in enumerate([220,425,630]):
    d.line((x,710,x,1035),fill=LIGHT,width=3)
    line(d,[(x,980),(x,735)],BLUE,8);line(d,[(x+20,735),(x+20,980)],BLUE,4)
    text(d,x-60,1045,f'启用枪 {i+1}',27)
text(d,85,1120,'公共 Y：下限取最大值，上限取最小值。',27)
text(d,85,1167,'各枪 X 参与情况仍由分枪使能决定。',27)

d.line((860,490,860,1230),fill=LIGHT,width=2)
text(d,920,490,'独立 Y：各枪分别在自己的范围往复',37)
text(d,920,552,'沿用上一张内侧分枪示例；以下为相对 Y 行程，未加入运行时缩减量',25)
ranges=[(507,979),(529,1001),(551,1023),(573,1045)]
colors=[TEAL,BLUE,'#7542a5','#a53474']
for i,((lo,hi),c) in enumerate(zip(ranges,colors)):
    x=1065+i*345
    ylo=1025-(lo-450)*.7;yhi=1025-(hi-450)*.7
    d.line((x,660,x,1040),fill=LIGHT,width=3)
    line(d,[(x,ylo),(x,yhi)],c,8);line(d,[(x+20,yhi),(x+20,ylo)],c,4)
    text(d,x-60,1060,f'G{i+2}',30);text(d,x-90,1110,f'{lo}～{hi}',26)
text(d,920,1170,'共享 Y 与独立 Y 使用同一换面主流程；差别在 Y 轴指令如何生成。',27)
text(d,65,1270,'二维示意的箭头只表达各轴往复范围；实际 X-Y 轨迹由速度、加减速和到位反馈共同决定。',28)
text(d,65,1330,'可选 rect 模式才使用“X 横扫 → Y 步进”的分层轨迹；当前配置为 2d，不能把该轨迹当作当前路径。',26)
save(im,'xn_side_02_各轴路径生成_白底.png')

im,d=canvas('xn_side  /  换面、收枪与特殊分支','柜体状态机补充｜正常主线见图 1；本页说明哪些条件会改变路线')
box(d,65,215,1160,295,'A  每次收枪：先退 X，再允许后续换面',[
 '收枪命令：X → 外侧等待位，喷涂状态置 0。',
 '收枪期间每根 Y、R 保持自己的当前位置。',
 'X 未到位：Z 保持工作跟随；X 到位：Z 转向安全目标。',
 '收枪阶段以 X 到位放行；下一等待阶段再下发对应 R 角度。'])
box(d,1305,215,1190,295,'B  内腔背板喷涂开关',[
 '当前关闭：前内侧完成 → 收枪 → 等后内侧 → 后内侧喷涂。',
 '若开启：前内侧完成后直接进入背板喷涂，不先收枪。',
 '背板喷涂：X 定位到内腔深处，R = 180°，Y 往复。',
 '后内侧到达 → 后内侧喷涂；已越过后内侧 → 直接收枪。'])
box(d,65,575,1160,295,'C  按列筛选与无启用枪',[
 '按 inside_data 顺序寻找可进入列；每列使用自己的枪组。',
 '已越过本列后边界：跳到下一可进入列。',
 '本列无启用枪且背板关闭：转入等待后外侧。',
 '本列无启用枪且背板开启：存在借用外侧枪组的背板分支。'])
box(d,1305,575,1190,295,'D  错过工件与安全退出',[
 '柜体等待前外侧时已进入安全区：转入错过工件处理。',
 '保持安全目标；待柜体后缘通过后再移除该设备工件。',
 '等待后外侧时已越过：直接完成；正常后外侧喷完才归位。',
 '自动关闭、伺服或激光异常：由上层统一安全处理。'])
box(d,65,935,2430,245,'E  内腔准入条件：设计公式与当前代码问题',[
 '设计意图：列 Z 跨度 > 前偏移 + 后偏移 + 2 × 喷枪半径 + 2 × 到位容差。',
 '当前 _get_inside_enter_threshold() 引用了本函数未定义的 inside_z_span，调用时触发 NameError。',
 '因此进入内侧分支前会受阻；图中流程是状态机设计表达。本次仅绘图，没有修改设备控制代码。'],ORANGE)
text(d,65,1240,'图 1、图 2 聚焦此前柜体场景。xn_side 另有平板模式：外侧二维喷涂至后缘，并支持相邻平板衔接。',27)
text(d,65,1300,'轴角度按当前 side_rotate_enabled=1 标注；关闭旋转功能时规划角度会统一变为 0°。',27)
text(d,65,1360,'依据：MotionXNSidePlanning.py、MotionReciprocate.py、MotionToTarget.py、SprayConfig.toml。',23)
save(im,'xn_side_03_换面与分支说明_白底.png')

# Reproduce only the affected method, without loading hardware or altering control code.
src=(ROOT/'model/motionplan/MotionXNSidePlanning.py').read_text(encoding='utf-8')
tree=ast.parse(src);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MotionXNSidePlanning')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_get_inside_enter_threshold')
ns={};exec(compile(ast.Module(body=[method],type_ignores=[]),'<isolated-source-method>','exec'),ns)
try:ns['_get_inside_enter_threshold'](type('Probe',(),{'spray_pos_tolerance':10})(),{'machine_cfg':{},'runtime_cfg':{}})
except NameError as exc:proof=str(exc)
else:raise AssertionError('Expected undefined-name failure was not reproduced')
(OUT/'xn_side_路径规划说明.md').write_text('''# xn_side 自动路径规划图

白底、黑字，2560×1440，16:9。仅表达 xn_side；主图聚焦柜体场景。

当前配置：xn_side_y_mode=1，side_reciprocate_mode="2d"，side_2d_cycle_axis="x"，side_back_end_face_enabled=0，side_rotate_enabled=1。

1. 总流程：分枪结果 → 自动条件 → 等前外侧 → 前外喷涂 → 收枪 → 各内侧列 → 后外喷涂 → 安全归位。
2. 路径生成：枪组提供Y范围与启用；X范围按工件边界扣偏移及安装位置，执行轴限位；二维模式X/Y同时往复，按反馈换向。
3. 换面与分支：收枪的轴约束、背板开关、漏过工件和无枪分支。

这不是设备仿真或实机通过证明。没有修改运动控制代码。内腔进枪函数存在运行阻断：
'''+proof+'''

已单独提取当前源码中的 _get_inside_enter_threshold 方法，用最小输入执行复现。其返回语句比较了本函数内未定义的 inside_z_span；外层 _can_enter_inside_column 又将其返回值当作阈值使用。图中公式标为设计意图，不能当作当前已可执行行为。

源码：
- model/motionplan/MotionCompleteWorkpiecePlanning.py
- model/motionplan/MotionXNSidePlanning.py
- model/motionplan/MotionReciprocate.py
- model/motionplan/MotionToTarget.py
- model/tomls/SprayConfig.toml
''',encoding='utf-8')
print('Verified isolated source failure:',proof)
for p in OUT.glob('xn_side_*.png'):print(p.name)
