"""Render reference-sized cabinet diagrams from the current distributors."""
import sys, types, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# The distributors only need the config dictionary here; avoid loading unrelated UI dependencies.
stub = types.ModuleType('model.utils.TomlLoader')
stub.TomlLoader = type('TomlLoader', (), {'load': staticmethod(lambda path: {})})
sys.modules['model.utils.TomlLoader'] = stub
from model.dataprocess.complete_workpiece.gun_distributors.XNIndependentYGunDistributor import XNIndependentYGunDistributor
from model.dataprocess.complete_workpiece.gun_distributors.XNSharedYGunDistributor import XNSharedYGunDistributor
from model.formats.complete_workpiece.BlockDataFormat import BlockData, OutsideData, InsideData, SubInsideData
from PIL import Image, ImageDraw, ImageFont

OUT = ROOT / 'output' / 'Y分枪逻辑图'
OUT.mkdir(exist_ok=True)
BG='#ffffff'; FG='#000000'; MUT='#525c66'; GRID='#dce2e8'; CYAN='#007e88'; YELLOW='#a46500'; RED='#b02020'
COLORS=['#b65b00','#00818a','#1265b0','#6748b5','#aa3476','#4b7f15']
FONT='C:/Windows/Fonts/msyh.ttc'
def font(s): return ImageFont.truetype(FONT,s)
def txt(d,xy,s,size=25,fill=FG): d.text(xy,s,font=font(size),fill=FG)
def dash(d,xy,fill=YELLOW,width=2):
    x1,y1,x2,y2=xy
    if y1==y2:
        for x in range(int(x1),int(x2),14): d.line((x,y1,min(x+7,x2),y2),fill=fill,width=width)
    else:
        for y in range(int(min(y1,y2)),int(max(y1,y2)),14): d.line((x1,y,x2,min(y+7,max(y1,y2))),fill=fill,width=width)
def arrow(d,x,y1,y2,c,width=5):
    d.line((x,y1,x,y2),fill=c,width=width)
    for y,sign in [(y1,1),(y2,-1)]:
        d.polygon([(x,y),(x-7,y+sign*12),(x+7,y+sign*12)],fill=c)

data=BlockData(outside_data=[OutsideData(outside_y_min=2299,outside_y_max=4582)],
    inside_data=[InsideData(inside_id=0,subinside_datalist=[SubInsideData(subinside_y_min=2407,subinside_y_max=4494)])])
cases={}
for side,origins in [('outside',[1550,2000,2400,2900,3350,3800]),('inside',[1550,2000,2450,2900,3350])]:
    cfg=dict(spray_num=len(origins),origin_pos=origins,out_up_y_offset=100,out_down_y_offset=100,
             in_up_y_offset=100,in_down_y_offset=100,max_limit_pos=[1000,1500])
    for mode,cls in [('shared',XNSharedYGunDistributor),('independent',XNIndependentYGunDistributor)]:
        obj=cls.__new__(cls);obj.spray_cfg={'min_recip_distance':60}
        group=next(g for g in obj.distribute(data,cfg,450) if g.group_type==side)
        cases[side,mode]={'origins':origins,'span':obj._resolve_scan_span(origins,450),'guns':group.gundata_list}

def panel(d,ox,side,mode):
    case=cases[side,mode]; origins=case['origins'];guns=case['guns'];span=case['span']
    title=('共享 Y' if mode=='shared' else '独立 Y')+' · '+('外侧' if side=='outside' else '内侧')
    txt(d,(ox+35,175),title,36)
    txt(d,(ox+35,228),f'扫描步距 = 相邻原点最小差 = {span} mm',23,MUT)
    xmin=ox+140; xmax=ox+1080; ytop=320; ybot=975
    def yy(v): return ybot-(v-1300)/3900*(ybot-ytop)
    for v in range(1500,5001,500):
        y=yy(v);d.line((xmin-10,y,xmax,y),fill=GRID,width=1);txt(d,(ox+35,y-13),str(v),20,MUT)
    txt(d,(ox+35,280),'绝对高度 / mm',20,MUT)
    # Same cabinet envelope and inferred interior opening in all panels.
    cx=xmin+15;cw=115
    d.rectangle((cx,yy(4582),cx+cw,yy(2299)),outline=MUT,width=3)
    d.rectangle((cx+13,yy(4494),cx+cw-13,yy(2407)),outline='#8a949e',width=2)
    lo,hi=(2199,4682) if side=='outside' else (2507,4394)
    for v in [lo,hi]:
        dash(d,(cx-12,yy(v),xmax,yy(v)))
        txt(d,(cx+8,yy(v)-31),str(v),23,YELLOW)
    d.line((cx+cw+8,yy(lo),cx+cw+8,yy(hi)),fill=YELLOW,width=3)
    # Gun origin -> motion trace. Gray lower stem is positioning, colored arrow is enabled motion.
    for i,(o,g) in enumerate(zip(origins,guns)):
        x=xmin+220+i*125;c=COLORS[i] if g.gun_y_enable else '#617182'
        a=o+g.gun_y_downer;b=o+g.gun_y_upper
        dash(d,(cx+cw+15,yy(o),x,yy(o)),fill='#526475',width=1)
        d.ellipse((x-6,yy(o)-6,x+6,yy(o)+6),fill=MUT)
        if a!=o:d.line((x,yy(o),x,yy(a)),fill='#566879',width=2)
        if g.gun_y_enable:
            arrow(d,x,yy(b),yy(a),c,7)
        else:
            d.line((x-9,yy(a)-9,x+9,yy(a)+9),fill=MUT,width=3)
            d.line((x-9,yy(a)+9,x+9,yy(a)-9),fill=MUT,width=3)
        txt(d,(x-20,985),f'G{i+1}',25,c)
        txt(d,(x-32,1022),str(o),20,MUT)
    txt(d,(ox+35,1067),'枪号    状态       Y 轴相对行程          喷涂绝对高度',23,MUT)
    for i,(o,g) in enumerate(zip(origins,guns)):
        y=1110+i*43;c=COLORS[i] if g.gun_y_enable else MUT
        state='启用' if g.gun_y_enable else '关闭'
        absolute=f'{o+g.gun_y_downer} ～ {o+g.gun_y_upper}' if g.gun_y_enable else '—'
        txt(d,(ox+35,y),f'G{i+1}',23,c);txt(d,(ox+137,y),state,23,c)
        txt(d,(ox+272,y),f'{g.gun_y_downer} ～ {g.gun_y_upper}',23,c)
        txt(d,(ox+570,y),absolute,23,c)
    return case

def render(side):
    im=Image.new('RGB',(2400,1660),BG);d=ImageDraw.Draw(im)
    name='外侧' if side=='outside' else '内侧'
    txt(d,(55,32),f'当前软件分枪逻辑  /  {name}对照',48)
    sub='按旧图算式反推：柜体外边界 2299～4582；内腔边界 2407～4494；单位 mm'
    txt(d,(55,105),sub,27,MUT)
    txt(d,(55,146),'演示条件：上下偏移各 100；Y 行程限位暂设 1500；原点沿用各自参考图，与当前设备配置有别。',21,YELLOW)
    d.line((1200,175,1200,1400),fill=GRID,width=3)
    for ox,mode in [(20,'shared'),(1220,'independent')]:panel(d,ox,side,mode)
    if side=='outside':
        notes=[
          '共享 Y：目标 2199～4682 → 选 G2～G6；各枪统一往复 0～400。',
          '独立 Y：floor(2483 / 400) = 6 把；初始分段 413，随后执行逐枪防撞范围约束。',
          '注意：共享 Y 最高只能喷到 4200，顶部仍缺 482；G3/G4、G4/G5、G5/G6 之间各有 100 / 50 / 50 空档。',
          '独立 Y 的实际范围经约束变为各枪 649～1062；本例有局部空档、重叠及顶部超出，图中保留真实计算结果。']
    else:
        notes=[
          '共享 Y：安全区 2507～4394，跨度 1887 ≥ 450；仅启用完整窗口严格落在安全区内的 G4、G5。',
          '独立 Y：floor(1887 / 450) = 4 把；从 G2 连续用到 G5；round(1887 / 4) = 472。',
          '本例独立 Y：G2 2507～2979 → G3 2979～3451 → G4 3451～3923 → G5 3923～4395。',
          '注意：共享 Y 并未覆盖整个内腔安全区；独立 Y 末端因取整比 4394 高 1 mm。多列内腔按列分别分枪。']
    d.line((55,1402,2345,1402),fill=GRID,width=2)
    for j,s in enumerate(notes): txt(d,(55,1422+j*43),s,24,RED if j>=2 else FG)
    txt(d,(55,1608),'图例：● 原点   彩色线：启用往复   × 关闭   棕色虚线：目标/安全边界；灰色细线：定位段；关闭枪记录不表示共享机构静止。',22,MUT)
    p=OUT/f'{name}_共享Y与独立Y_白底.png';im.save(p,dpi=(200,200));return p

paths=[render('outside'),render('inside')]
report={f'{s}_{m}':dict(origins=v['origins'],scan_span=v['span'],guns=[vars(g) for g in v['guns']]) for (s,m),v in cases.items()}
(OUT/'计算结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'说明.md').write_text('''# 当前软件分枪逻辑图

图片直接调用当前 XNSharedYGunDistributor / XNIndependentYGunDistributor 计算，不修改算法。

## 演示输入与推定
- 沿用参考图原点。外侧 1550、2000、2400、2900、3350、3800；内侧 1550、2000、2450、2900、3350。原图两组原点不同，因此分别用于对应图，不能视为同一硬件配置。
- 依据旧图算式反推：外侧目标下限 1550+649=2199，上限 2199+2483=4682。扣除上下各100的扩边，柜体外边界为2299～4582。
- 内侧安全区下限2000+507=2507，上限2507+1887=4394。恢复上下各100安全缩边，内腔边界为2407～4494。
- 上述绝对柜体边界是推定，原图未直接给出；如实际柜体边界不同，应重新计算。
- Y轴行程上限暂设1500，短行程阈值60。1500为演示假设，不代表仓库当前设备配置；降低限位会改变独立Y结果。
- 配置gun_distance输入450，但当前两套算法优先使用相邻原点最小正差：外侧400、内侧450。
- 喷枪图号G1从最低原点开始；对应代码gun_id=0。
- 彩色线表示启用枪的绝对高度范围，不表示完整有效涂层覆盖。喷幅、轨迹速度、遮挡和实际机械同步不在此图内。
- 关闭枪的相对行程0仅为分枪记录；共享轴上关闭枪也会随机构运动。
- 当前配置xn_side_y_mode=1；共享Y图为同一代码库模式0的对照，图示输入沿用用户参考图而非当前MachineConfig配置。

## 代码
model/dataprocess/complete_workpiece/gun_distributors/XNSharedYGunDistributor.py
model/dataprocess/complete_workpiece/gun_distributors/XNIndependentYGunDistributor.py
model/dataprocess/complete_workpiece/GunDistributor.py
''',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
print('\n'.join(map(str,paths)))
