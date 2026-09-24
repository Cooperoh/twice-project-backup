"""Project-wide static values and runtime defaults."""

# 领机巡航航段和编队基础参数
LEG_DIST        =   20_000  
TRAIL_DIST      =   2000            # 默认编队间距，地面站下发 spacing 时会覆盖它。
REACH_R         =   1000            # 领机距离航段目标 <= REACH_R * 2 时，认为该航段到达。
CHECK_INT       =   0.5            
CRUISE_SPEED    =   135             # 领机巡航速度，m/s；本次调整前为 120。

# 从机速度修正参数
"""
    fwd_err = 从机当前位置相对队形槽位点的沿航向距离
    fwd_err < 0 表示从机落后槽位，需要加速；
    fwd_err > 0 表示从机超前槽位，需要减速。
    abs(fwd_err) < FOLLOW_ERR_DEADBAND 时不修正，tgt_spd = lead_speed。
    否则：
        raw_spd = lead_speed - FOLLOW_SPEED_GAIN * fwd_err
        tgt_spd = max( FOLLOW_SPEED_MIN,  min(FOLLOW_SPEED_MAX, raw_spd)  )
"""
FOLLOW_SPEED_BASE   =   135          # 从机默认速度，m/s；本次调整前为 120。
FOLLOW_SPEED_MIN    =   100          # 从机速度下限，m/s；本次调整前为 90。
FOLLOW_SPEED_MAX    =   170          # 从机速度上限，m/s；本次调整前为 160。
FOLLOW_SPEED_GAIN   =   0.025         # 速度修正增益，定义为可用速度差/饱和误差距离，比如追赶速度40，落后距离最大1600，那么对应就是0.025。（注：似乎受到了油门变化率的限制，导致速度变化不跟手 ←-- 真巧px4那边算出来的也是这个值，难道固定翼都一样）
FOLLOW_ERR_DEADBAND =   200           # 前后误差死区，小于该值时跟随领机速度。

# 从机前视点参数，避免固定翼直接追队形槽位点导致目标落到机体后方。
"""
    前视距离 delta 的计算：
        raw_delta = spacing * LOOKAHEAD_SPACING_GAIN + lead_speed * LOOKAHEAD_SPEED_TIME
        delta = max(LOOKAHEAD_MIN, min(LOOKAHEAD_MAX, raw_delta))
    其中 spacing 是当前编队间距，lead_speed 是领机广播速度。
"""
LOOKAHEAD_SPACING_GAIN  =   1.2       # 间距对前视距离的比例系数
LOOKAHEAD_SPEED_TIME    =   1.5       # 按领机速度外推的前视时间
LOOKAHEAD_MIN           =   2000      # 前视距离下限
LOOKAHEAD_MAX           =   4000      # 前视距离上限

# 配置合并时使用的默认值；逐机不同的部署参数仍放在 config.py。
DEFAULT_GROUP               =   0
DEFAULT_IS_LEADER           =   0
DEFAULT_FORMATION_TYPE      =   1
DEFAULT_FORMATION_SPACING   =   TRAIL_DIST
DEFAULT_SERIAL_TIMEOUT      =   0.1
DEFAULT_UDP_TIMEOUT         =   0.1
DEFAULT_READ_SIZE           =   128
