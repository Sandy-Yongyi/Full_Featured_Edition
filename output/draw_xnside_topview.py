from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont
O=Path(__file__).resolve().parent/'Y分枪逻辑图'
im=Image.new('RGB',(2880,1620),'white');d=ImageDraw.Draw(im)
F='C:/Windows/Fonts/msyh.ttc';B='#1263a2';T='#007a70';G='#60707c';L='#d9e1e7'
def tx(x,y,s,n=32):d.text((x,y),s,font=ImageFont.truetype(F,n),fill='black')
def ar(p,c=B,w=5):
 d.line(p,fill=c,width=w)
 a,b=p[-2];x,y=p[-1];q=math.atan2(y-b,x-a)
 d.polygon([(x,y),(x-20*math.cos(q-.45),y-20*math.sin(q-.45)),(x-20*math.cos(q+.45),y-20*math.sin(q+.45))],fill=c)
def badge(x,y,s,c=B):
 d.rounded_rectangle((x-58,y-29,x+58,y+29),radius=23,fill='white',outline=c,width=4)
 f=ImageFont.truetype(F,29);bb=d.textbbox((0,0),s,font=f);d.text((x-(bb[2]-bb[0])/2,y-21),s,font=f,fill='black')
tx(70,35,'xn_side 自动喷涂步骤｜柜体俯视示意图',54)
tx(70,112,'以一个内腔的柜体为例：前内侧往复后不收枪，直接喷涂背板，再进行后内侧往复。',31)
# Cabinet moves left: its leading/front wall is left, trailing/rear wall right.
ar([(1920,217),(1020,217)],G,6);tx(1210,165,'工件输送方向（Z）',32)
x1,x2,yt,yb=910,2100,300,615
d.rectangle((x1,yt,x2,yt+42),fill='#edf1f4',outline=G,width=3)
d.rectangle((x1,yt,x1+48,yb),fill='#edf1f4',outline=G,width=3)
d.rectangle((x2-48,yt,x2,yb),fill='#edf1f4',outline=G,width=3)
tx(1320,365,'柜体内腔',45);tx(1260,425,'柜体背板',29)
tx(1280,550,'开口朝向 xn_side',30)
tx(680,340,'前外端面',31);tx(980,480,'前内端面',31)
tx(1770,480,'后内端面',31);tx(2160,340,'后外端面',31)
# Action-location callouts.
badge(720,440,'1 / 2');ar([(780,440),(875,440),(910,485)],B,4)
badge(1025,680,'3 / 4',T);ar([(1025,650),(1000,585),(958,550)],T,4)
badge(1975,680,'6',T);ar([(1975,650),(2010,585),(2052,550)],T,4)
badge(1770,390,'5',T);ar([(1770,360),(1770,342)],T,4)
badge(2290,440,'7 / 8');ar([(2230,440),(2145,440),(2100,485)],B,4)
# One schematic side unit, no duplicated physical machines.
d.rounded_rectangle((1360,660,1670,740),radius=12,fill='#edf1f4',outline=G,width=3)
d.rectangle((1495,620,1535,660),fill='#edf1f4',outline=G,width=3)
ar([(1515,645),(1515,601)],T,4)
tx(1380,680,'xn_side 设备',30)
badge(1760,720,'9',G);d.line((1700,720,1670,720),fill=G,width=3)
tx(85,550,'俯视图中：',29);tx(85,595,'X：进枪 / 收枪方向',29)
tx(85,640,'Y：上下升降，垂直图面',29);tx(85,685,'端面往复包含 X、Y 运动',29)
ar([(570,690),(570,560)],G,4);tx(600,584,'X',30)
tx(85,765,'图中编号标记动作对应的表面或阶段，不代表同时摆放多台设备，也不代表连续空间轨迹。',27)
d.line((70,818,2810,818),fill=L,width=2)
steps=[
 ('1  等待前外端面',['X 到等待位，Y 到分枪下限','R = −90°；等待前外端面到达']),
 ('2  前外端面往复',['使用外侧分枪组进行 X / Y 往复','达到外侧配置次数后结束']),
 ('3  收枪 → 等待前内端面',['先收 X，Y / R 保持；再准备内侧','R = +90°；等待本列前内端面']),
 ('4  前内端面往复',['切换本列内侧分枪组，X / Y 往复','达到内侧次数后不收枪，直接喷背板']),
 ('5  背板喷涂（不收枪）',['X 定位至背板喷涂位，R = 180°','Y 往复；后内端面到达后进入步骤 6']),
 ('6  后内端面往复',['背板喷涂后直接转入，R = −90°','本列内侧枪组 X / Y 往复至配置次数']),
 ('7  收枪 → 等待后外端面',['有下一内腔列则返回步骤 3','无下一列：R = +90°，等后外端面']),
 ('8  后外端面往复',['切回外侧分枪组进行 X / Y 往复','达到外侧配置次数后结束']),
 ('9  安全归位',['先 X 回安全位，再回 Y / R 等轴','归位完成，结束当前设备工件任务'])]
for i,(title,body) in enumerate(steps):
 row=i//3;col=i%3;x=75+col*945;y=850+row*217
 c=T if i in [3,4,5] else B
 d.rounded_rectangle((x,y,x+875,y+175),radius=12,outline=c,width=3,fill='white')
 tx(x+23,y+16,title,34)
 for j,s in enumerate(body):tx(x+23,y+72+j*43,s,28)
 if col<2:ar([(x+882,y+88),(x+934,y+88)],G,4)
 if col==2 and row<2:
  # Explicit sequence continuation text avoids a long line across all columns.
  tx(x+480,y+182,'下一行继续 ↓',24)
tx(75,1518,'说明：按包含背板喷涂的正常流程绘制；前内侧 → 背板 → 后内侧连续执行，中间不收枪。',27)
tx(75,1565,'代码核查：内腔准入函数存在未定义变量，流程图表达状态机设计；本次未修改控制代码。',25)
p=O/'xn_side_柜体俯视步骤图_白底.png';im.save(p,dpi=(200,200));print(p)
im.crop((50,835,2835,1490)).save(O/'xn_side_喷涂步骤_含背板_白底.png',dpi=(200,200))
