
from __future__ import annotations
import logging
from typing import Dict, List, Set, Any, Optional
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)

TYPE_CONTROLLABLE = "controllable"
TYPE_READ_ONLY = "read_only"
TYPE_SERVICE_ONLY = "service_only"

PRIORITY_ESSENTIAL = 1
PRIORITY_COMMON = 2
PRIORITY_STANDARD = 3
PRIORITY_EXTENDED = 4
PRIORITY_SPECIALIZED = 5


@dataclass
class ServiceParam:

    name: str
    description: str
    required: bool = False
    param_type: str = "string"
    default: Any = None
    enum: List[Any] = None
    min_value: float = None
    max_value: float = None


@dataclass
class ServiceDef:

    name: str
    description: str
    params: List[ServiceParam] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    expected_state: str | None = None
    toggle_states: tuple[str, str] | None = None


@dataclass
class DomainDef:

    domain: str
    domain_type: str
    priority: int
    description: str
    services: List[ServiceDef] = field(default_factory=list)
    device_classes: List[str] = field(default_factory=list)
    action_services: Dict[str, str] = field(default_factory=dict)


DOMAIN_REGISTRY: Dict[str, DomainDef] = {}


def _register_domains():

    global DOMAIN_REGISTRY


    DOMAIN_REGISTRY["light"] = DomainDef(
        domain="light",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_ESSENTIAL,
        description="灯光控制",
        services=[
            ServiceDef(
                name="turn_on",
                description="开灯",
                aliases=["on"],
                expected_state="on",
                params=[
                    ServiceParam("brightness", "亮度 (0-255)", param_type="number", min_value=0, max_value=255),
                    ServiceParam("brightness_pct", "亮度百分比 (0-100)", param_type="number", min_value=0, max_value=100),
                    ServiceParam("color_temp", "色温 (Kelvin)", param_type="number"),
                    ServiceParam("color_temp_kelvin", "色温 (Kelvin)", param_type="number", min_value=2000, max_value=6500),
                    ServiceParam("rgb_color", "RGB颜色 [r,g,b]", param_type="array"),
                    ServiceParam("hs_color", "HS颜色 [hue, saturation]", param_type="array"),
                    ServiceParam("transition", "过渡时间(秒)", param_type="number", min_value=0),
                    ServiceParam("effect", "灯光效果", param_type="string"),
                ]
            ),
            ServiceDef(name="turn_off", description="关灯", aliases=["off"], expected_state="off"),
            ServiceDef(name="toggle", description="切换开关状态", toggle_states=("on", "off")),
        ],
        device_classes=["light"]
    )

    DOMAIN_REGISTRY["switch"] = DomainDef(
        domain="switch",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_ESSENTIAL,
        description="开关控制",
        services=[
            ServiceDef(name="turn_on", description="打开", aliases=["on"], expected_state="on"),
            ServiceDef(name="turn_off", description="关闭", aliases=["off"], expected_state="off"),
            ServiceDef(name="toggle", description="切换", toggle_states=("on", "off")),
        ],
        device_classes=["outlet", "switch"]
    )

    DOMAIN_REGISTRY["climate"] = DomainDef(
        domain="climate",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_ESSENTIAL,
        description="空调/温控",
        services=[
            ServiceDef(name="turn_on", description="开启", expected_state="on"),
            ServiceDef(name="turn_off", description="关闭", expected_state="off"),
            ServiceDef(
                name="set_temperature",
                description="设置温度",
                params=[
                    ServiceParam("temperature", "目标温度", required=True, param_type="number"),
                    ServiceParam("target_temp_high", "最高温度", param_type="number"),
                    ServiceParam("target_temp_low", "最低温度", param_type="number"),
                    ServiceParam("hvac_mode", "模式", param_type="string",
                               enum=["off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"]),
                ]
            ),
            ServiceDef(
                name="set_hvac_mode",
                description="设置模式",
                params=[
                    ServiceParam("hvac_mode", "模式", required=True, param_type="string",
                               enum=["off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"]),
                ]
            ),
            ServiceDef(
                name="set_fan_mode",
                description="设置风速",
                params=[
                    ServiceParam("fan_mode", "风速", required=True, param_type="string",
                               enum=["auto", "low", "medium", "high"]),
                ]
            ),
        ]
    )

    DOMAIN_REGISTRY["cover"] = DomainDef(
        domain="cover",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_ESSENTIAL,
        description="窗帘/卷帘",
        services=[
            ServiceDef(name="open_cover", description="打开", aliases=["open"], expected_state="open"),
            ServiceDef(name="close_cover", description="关闭", aliases=["close"], expected_state="closed"),
            ServiceDef(name="stop_cover", description="停止", aliases=["stop"]),
            ServiceDef(name="toggle", description="切换"),
            ServiceDef(
                name="set_cover_position",
                description="设置位置",
                params=[
                    ServiceParam("position", "位置 (0-100)", required=True, param_type="number", min_value=0, max_value=100),
                ]
            ),
            ServiceDef(
                name="set_cover_tilt_position",
                description="设置倾斜角度",
                params=[
                    ServiceParam("tilt_position", "倾斜 (0-100)", required=True, param_type="number", min_value=0, max_value=100),
                ]
            ),
            ServiceDef(name="open_cover_tilt", description="打开倾斜/天窗叶片", aliases=["open_tilt"]),
            ServiceDef(name="close_cover_tilt", description="关闭倾斜/天窗叶片", aliases=["close_tilt"]),
            ServiceDef(name="stop_cover_tilt", description="停止倾斜/天窗叶片", aliases=["stop_tilt"]),
            ServiceDef(name="toggle_tilt", description="切换倾斜/天窗叶片"),
        ],
        device_classes=["awning", "blind", "curtain", "damper", "door", "garage", "gate", "shade", "shutter", "window"],
        action_services={"turn_on": "open_cover", "turn_off": "close_cover"}
    )


    DOMAIN_REGISTRY["fan"] = DomainDef(
        domain="fan",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_COMMON,
        description="风扇",
        services=[
            ServiceDef(name="turn_on", description="开启", expected_state="on"),
            ServiceDef(name="turn_off", description="关闭", expected_state="off"),
            ServiceDef(name="toggle", description="切换", toggle_states=("on", "off")),
            ServiceDef(
                name="set_percentage",
                description="设置风速百分比",
                params=[
                    ServiceParam("percentage", "风速 (0-100)", required=True, param_type="number", min_value=0, max_value=100),
                ]
            ),
            ServiceDef(name="oscillate", description="摆头", params=[
                ServiceParam("oscillating", "是否摆头", required=True, param_type="boolean"),
            ]),
            ServiceDef(
                name="set_direction",
                description="设置方向",
                params=[
                    ServiceParam("direction", "方向", required=True, param_type="string", enum=["forward", "reverse"]),
                ]
            ),
        ]
    )

    DOMAIN_REGISTRY["media_player"] = DomainDef(
        domain="media_player",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_COMMON,
        description="媒体播放器",
        services=[
            ServiceDef(name="turn_on", description="开启", expected_state="on"),
            ServiceDef(name="turn_off", description="关闭", expected_state="off"),
            ServiceDef(name="toggle", description="切换", toggle_states=("on", "off")),
            ServiceDef(name="media_play", description="播放", aliases=["play"], expected_state="playing"),
            ServiceDef(name="media_pause", description="暂停", aliases=["pause"], expected_state="paused"),
            ServiceDef(name="media_stop", description="停止", aliases=["stop"]),
            ServiceDef(name="media_next_track", description="下一曲", aliases=["next"]),
            ServiceDef(name="media_previous_track", description="上一曲", aliases=["previous"]),
            ServiceDef(
                name="volume_set",
                description="设置音量",
                params=[
                    ServiceParam("volume_level", "音量 (0-1)", required=True, param_type="number", min_value=0, max_value=1),
                ]
            ),
            ServiceDef(name="volume_up", description="音量+"),
            ServiceDef(name="volume_down", description="音量-"),
            ServiceDef(name="volume_mute", description="静音", params=[
                ServiceParam("is_volume_muted", "是否静音", required=True, param_type="boolean"),
            ]),
            ServiceDef(
                name="play_media",
                description="播放媒体",
                params=[
                    ServiceParam("media_content_id", "媒体ID/URL", required=True, param_type="string"),
                    ServiceParam("media_content_type", "媒体类型", required=True, param_type="string",
                               enum=["music", "video", "image", "playlist", "channel"]),
                ]
            ),
        ],
        device_classes=["tv", "speaker", "receiver"],
        action_services={"turn_on": "media_play", "turn_off": "media_stop"}
    )

    DOMAIN_REGISTRY["lock"] = DomainDef(
        domain="lock",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_COMMON,
        description="门锁",
        services=[
            ServiceDef(name="lock", description="上锁", expected_state="locked"),
            ServiceDef(name="unlock", description="解锁", expected_state="unlocked"),
            ServiceDef(name="open", description="打开（支持的锁）"),
        ],
        action_services={"turn_on": "unlock", "turn_off": "lock"}
    )

    DOMAIN_REGISTRY["vacuum"] = DomainDef(
        domain="vacuum",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_COMMON,
        description="扫地机器人",
        services=[
            ServiceDef(name="start", description="开始清扫", expected_state="cleaning"),
            ServiceDef(name="stop", description="停止", expected_state="idle"),
            ServiceDef(name="pause", description="暂停", expected_state="paused"),
            ServiceDef(name="return_to_base", description="返回充电座", aliases=["return_home", "dock"], expected_state="returning"),
            ServiceDef(name="locate", description="定位（发出声音）"),
            ServiceDef(
                name="set_fan_speed",
                description="设置吸力",
                params=[
                    ServiceParam("fan_speed", "吸力档位", required=True, param_type="string"),
                ]
            ),
            ServiceDef(
                name="send_command",
                description="发送命令",
                params=[
                    ServiceParam("command", "命令", required=True, param_type="string"),
                    ServiceParam("params", "参数", param_type="object"),
                ]
            ),
        ],
        action_services={"turn_on": "start", "turn_off": "return_to_base"}
    )


    DOMAIN_REGISTRY["sensor"] = DomainDef(
        domain="sensor",
        domain_type=TYPE_READ_ONLY,
        priority=PRIORITY_STANDARD,
        description="传感器（只读）",
        services=[],
        device_classes=[
            "apparent_power", "aqi", "atmospheric_pressure", "battery", "carbon_dioxide",
            "carbon_monoxide", "current", "data_rate", "data_size", "date", "distance",
            "duration", "energy", "enum", "frequency", "gas", "humidity", "illuminance",
            "irradiance", "moisture", "monetary", "nitrogen_dioxide", "nitrogen_monoxide",
            "nitrous_oxide", "ozone", "pm1", "pm10", "pm25", "power", "power_factor",
            "precipitation", "precipitation_intensity", "pressure", "reactive_power",
            "signal_strength", "sound_pressure", "speed", "sulphur_dioxide", "temperature",
            "timestamp", "volatile_organic_compounds", "voltage", "volume", "water", "weight", "wind_speed"
        ]
    )

    DOMAIN_REGISTRY["binary_sensor"] = DomainDef(
        domain="binary_sensor",
        domain_type=TYPE_READ_ONLY,
        priority=PRIORITY_STANDARD,
        description="二元传感器（只读）",
        services=[],
        device_classes=[
            "battery", "battery_charging", "carbon_monoxide", "cold", "connectivity",
            "door", "garage_door", "gas", "heat", "light", "lock", "moisture", "motion",
            "moving", "occupancy", "opening", "plug", "power", "presence", "problem",
            "running", "safety", "smoke", "sound", "tamper", "update", "vibration", "window"
        ]
    )


    DOMAIN_REGISTRY["script"] = DomainDef(
        domain="script",
        domain_type=TYPE_SERVICE_ONLY,
        priority=PRIORITY_EXTENDED,
        description="脚本",
        services=[
            ServiceDef(name="turn_on", description="执行脚本"),
            ServiceDef(name="turn_off", description="停止脚本"),
            ServiceDef(name="toggle", description="切换"),
            ServiceDef(name="reload", description="重新加载脚本"),
        ]
    )

    DOMAIN_REGISTRY["automation"] = DomainDef(
        domain="automation",
        domain_type=TYPE_SERVICE_ONLY,
        priority=PRIORITY_EXTENDED,
        description="自动化",
        services=[
            ServiceDef(name="turn_on", description="启用自动化", expected_state="on"),
            ServiceDef(name="turn_off", description="禁用自动化", expected_state="off"),
            ServiceDef(name="toggle", description="切换", toggle_states=("on", "off")),
            ServiceDef(name="trigger", description="触发自动化", params=[
                ServiceParam("skip_condition", "跳过条件检查", param_type="boolean", default=False),
            ]),
            ServiceDef(name="reload", description="重新加载自动化"),
        ]
    )

    DOMAIN_REGISTRY["scene"] = DomainDef(
        domain="scene",
        domain_type=TYPE_SERVICE_ONLY,
        priority=PRIORITY_EXTENDED,
        description="场景",
        services=[
            ServiceDef(name="turn_on", description="激活场景", aliases=["activate"]),
        ]
    )

    DOMAIN_REGISTRY["notify"] = DomainDef(
        domain="notify",
        domain_type=TYPE_SERVICE_ONLY,
        priority=PRIORITY_EXTENDED,
        description="通知服务",
        services=[
            ServiceDef(
                name="send_message",
                description="发送通知",
                params=[
                    ServiceParam("message", "消息内容", required=True, param_type="string"),
                    ServiceParam("title", "标题", param_type="string"),
                    ServiceParam("target", "目标", param_type="array"),
                    ServiceParam("data", "附加数据", param_type="object"),
                ]
            ),
        ]
    )

    DOMAIN_REGISTRY["tts"] = DomainDef(
        domain="tts",
        domain_type=TYPE_SERVICE_ONLY,
        priority=PRIORITY_EXTENDED,
        description="文字转语音",
        services=[
            ServiceDef(
                name="speak",
                description="朗读文字",
                params=[
                    ServiceParam("media_player_entity_id", "播放设备", required=True, param_type="string"),
                    ServiceParam("message", "文字内容", required=True, param_type="string"),
                    ServiceParam("language", "语言", param_type="string"),
                    ServiceParam("cache", "缓存", param_type="boolean", default=True),
                ]
            ),
        ]
    )

    DOMAIN_REGISTRY["input_boolean"] = DomainDef(
        domain="input_boolean",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="输入布尔值",
        services=[
            ServiceDef(name="turn_on", description="设为开", expected_state="on"),
            ServiceDef(name="turn_off", description="设为关", expected_state="off"),
            ServiceDef(name="toggle", description="切换", toggle_states=("on", "off")),
        ]
    )

    DOMAIN_REGISTRY["input_number"] = DomainDef(
        domain="input_number",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="输入数值",
        services=[
            ServiceDef(
                name="set_value",
                description="设置值",
                params=[
                    ServiceParam("value", "数值", required=True, param_type="number"),
                ]
            ),
            ServiceDef(name="increment", description="增加"),
            ServiceDef(name="decrement", description="减少"),
        ]
    )

    DOMAIN_REGISTRY["input_select"] = DomainDef(
        domain="input_select",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="输入选择",
        services=[
            ServiceDef(
                name="select_option",
                description="选择选项",
                params=[
                    ServiceParam("option", "选项", required=True, param_type="string"),
                ]
            ),
            ServiceDef(name="select_first", description="选择第一个"),
            ServiceDef(name="select_last", description="选择最后一个"),
            ServiceDef(name="select_next", description="选择下一个"),
            ServiceDef(name="select_previous", description="选择上一个"),
        ]
    )


    DOMAIN_REGISTRY["alarm_control_panel"] = DomainDef(
        domain="alarm_control_panel",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_SPECIALIZED,
        description="报警控制面板",
        services=[
            ServiceDef(name="alarm_disarm", description="撤防", params=[
                ServiceParam("code", "密码", param_type="string"),
            ]),
            ServiceDef(name="alarm_arm_home", description="在家布防", params=[
                ServiceParam("code", "密码", param_type="string"),
            ]),
            ServiceDef(name="alarm_arm_away", description="离家布防", params=[
                ServiceParam("code", "密码", param_type="string"),
            ]),
            ServiceDef(name="alarm_arm_night", description="夜间布防", params=[
                ServiceParam("code", "密码", param_type="string"),
            ]),
            ServiceDef(name="alarm_trigger", description="触发报警"),
        ]
    )

    DOMAIN_REGISTRY["camera"] = DomainDef(
        domain="camera",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_SPECIALIZED,
        description="摄像头",
        services=[
            ServiceDef(name="enable_motion_detection", description="启用移动侦测"),
            ServiceDef(name="disable_motion_detection", description="禁用移动侦测"),
            ServiceDef(name="snapshot", description="拍照", params=[
                ServiceParam("filename", "文件名", param_type="string"),
            ]),
            ServiceDef(name="record", description="录像", params=[
                ServiceParam("filename", "文件名", param_type="string"),
                ServiceParam("duration", "时长(秒)", param_type="number"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["humidifier"] = DomainDef(
        domain="humidifier",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_SPECIALIZED,
        description="加湿器",
        services=[
            ServiceDef(name="turn_on", description="开启"),
            ServiceDef(name="turn_off", description="关闭"),
            ServiceDef(name="toggle", description="切换"),
            ServiceDef(name="set_humidity", description="设置湿度", params=[
                ServiceParam("humidity", "目标湿度 (0-100)", required=True, param_type="number", min_value=0, max_value=100),
            ]),
            ServiceDef(name="set_mode", description="设置模式", params=[
                ServiceParam("mode", "模式", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["water_heater"] = DomainDef(
        domain="water_heater",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_SPECIALIZED,
        description="热水器",
        services=[
            ServiceDef(name="turn_on", description="开启"),
            ServiceDef(name="turn_off", description="关闭"),
            ServiceDef(name="set_temperature", description="设置温度", params=[
                ServiceParam("temperature", "目标温度", required=True, param_type="number"),
            ]),
            ServiceDef(name="set_operation_mode", description="设置模式", params=[
                ServiceParam("operation_mode", "模式", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["input_text"] = DomainDef(
        domain="input_text",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="输入文本",
        services=[
            ServiceDef(name="set_value", description="设置文本", params=[
                ServiceParam("value", "文本内容", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["input_datetime"] = DomainDef(
        domain="input_datetime",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="输入日期时间",
        services=[
            ServiceDef(name="set_datetime", description="设置日期时间", params=[
                ServiceParam("date", "日期 (YYYY-MM-DD)", param_type="string"),
                ServiceParam("time", "时间 (HH:MM:SS)", param_type="string"),
                ServiceParam("datetime", "日期时间", param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["button"] = DomainDef(
        domain="button",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="按钮",
        services=[
            ServiceDef(name="press", description="按下"),
        ]
    )

    DOMAIN_REGISTRY["number"] = DomainDef(
        domain="number",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="数值实体",
        services=[
            ServiceDef(name="set_value", description="设置值", params=[
                ServiceParam("value", "数值", required=True, param_type="number"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["select"] = DomainDef(
        domain="select",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="选择实体",
        services=[
            ServiceDef(name="select_option", description="选择选项", params=[
                ServiceParam("option", "选项", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["timer"] = DomainDef(
        domain="timer",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="计时器",
        services=[
            ServiceDef(name="start", description="开始", params=[
                ServiceParam("duration", "时长 (HH:MM:SS)", param_type="string"),
            ]),
            ServiceDef(name="pause", description="暂停"),
            ServiceDef(name="cancel", description="取消"),
            ServiceDef(name="finish", description="完成"),
            ServiceDef(name="change", description="修改时长", params=[
                ServiceParam("duration", "新时长", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["counter"] = DomainDef(
        domain="counter",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="计数器",
        services=[
            ServiceDef(name="increment", description="增加"),
            ServiceDef(name="decrement", description="减少"),
            ServiceDef(name="reset", description="重置"),
            ServiceDef(name="set_value", description="设置值", params=[
                ServiceParam("value", "数值", required=True, param_type="number"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["valve"] = DomainDef(
        domain="valve",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_COMMON,
        description="阀门",
        services=[
            ServiceDef(name="open_valve", description="打开阀门", expected_state="open"),
            ServiceDef(name="close_valve", description="关闭阀门", expected_state="closed"),
            ServiceDef(name="stop_valve", description="停止"),
            ServiceDef(name="set_valve_position", description="设置阀门位置", params=[
                ServiceParam("position", "位置 (0-100)", required=True, param_type="number", min_value=0, max_value=100),
            ]),
        ],
        device_classes=["water", "gas"],
        action_services={"turn_on": "open_valve", "turn_off": "close_valve"}
    )

    DOMAIN_REGISTRY["siren"] = DomainDef(
        domain="siren",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_SPECIALIZED,
        description="警报器",
        services=[
            ServiceDef(name="turn_on", description="开启警报", expected_state="on", params=[
                ServiceParam("tone", "警报音调", param_type="string"),
                ServiceParam("volume_level", "音量 (0-1)", param_type="number", min_value=0, max_value=1),
                ServiceParam("duration", "持续时间(秒)", param_type="number"),
            ]),
            ServiceDef(name="turn_off", description="关闭警报", expected_state="off"),
            ServiceDef(name="toggle", description="切换", toggle_states=("on", "off")),
        ]
    )

    DOMAIN_REGISTRY["lawn_mower"] = DomainDef(
        domain="lawn_mower",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_SPECIALIZED,
        description="割草机",
        services=[
            ServiceDef(name="start_mowing", description="开始割草", expected_state="mowing"),
            ServiceDef(name="pause", description="暂停", expected_state="paused"),
            ServiceDef(name="dock", description="返回基座", expected_state="docked"),
        ],
        action_services={"turn_on": "start_mowing", "turn_off": "dock"}
    )

    DOMAIN_REGISTRY["remote"] = DomainDef(
        domain="remote",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_COMMON,
        description="遥控器",
        services=[
            ServiceDef(name="turn_on", description="开启", expected_state="on"),
            ServiceDef(name="turn_off", description="关闭", expected_state="off"),
            ServiceDef(name="toggle", description="切换", toggle_states=("on", "off")),
            ServiceDef(name="send_command", description="发送命令", params=[
                ServiceParam("command", "命令", required=True, param_type="string"),
                ServiceParam("device", "目标设备", param_type="string"),
                ServiceParam("num_repeats", "重复次数", param_type="number"),
                ServiceParam("delay_secs", "延迟(秒)", param_type="number"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["update"] = DomainDef(
        domain="update",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="更新实体",
        services=[
            ServiceDef(name="install", description="安装更新", params=[
                ServiceParam("version", "版本号", param_type="string"),
                ServiceParam("backup", "安装前备份", param_type="boolean", default=True),
            ]),
            ServiceDef(name="skip", description="跳过此版本"),
            ServiceDef(name="clear_skipped", description="清除已跳过"),
        ]
    )

    DOMAIN_REGISTRY["weather"] = DomainDef(
        domain="weather",
        domain_type=TYPE_READ_ONLY,
        priority=PRIORITY_STANDARD,
        description="天气",
        services=[],
    )

    DOMAIN_REGISTRY["todo"] = DomainDef(
        domain="todo",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="待办事项",
        services=[
            ServiceDef(name="add_item", description="添加待办", params=[
                ServiceParam("item", "待办内容", required=True, param_type="string"),
                ServiceParam("due_date", "截止日期", param_type="string"),
                ServiceParam("description", "描述", param_type="string"),
            ]),
            ServiceDef(name="update_item", description="更新待办", params=[
                ServiceParam("item", "待办内容", required=True, param_type="string"),
                ServiceParam("rename", "新名称", param_type="string"),
                ServiceParam("status", "状态", param_type="string", enum=["needs_action", "completed"]),
            ]),
            ServiceDef(name="remove_item", description="删除待办", params=[
                ServiceParam("item", "待办内容", required=True, param_type="string"),
            ]),
            ServiceDef(name="get_items", description="获取列表", params=[
                ServiceParam("status", "筛选状态", param_type="string", enum=["needs_action", "completed"]),
            ]),
        ]
    )

    DOMAIN_REGISTRY["calendar"] = DomainDef(
        domain="calendar",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="日历",
        services=[
            ServiceDef(name="create_event", description="创建事件", params=[
                ServiceParam("summary", "事件标题", required=True, param_type="string"),
                ServiceParam("start_date_time", "开始时间", param_type="string"),
                ServiceParam("end_date_time", "结束时间", param_type="string"),
                ServiceParam("start_date", "开始日期(全天)", param_type="string"),
                ServiceParam("end_date", "结束日期(全天)", param_type="string"),
                ServiceParam("description", "描述", param_type="string"),
                ServiceParam("location", "地点", param_type="string"),
            ]),
            ServiceDef(name="get_events", description="获取事件", params=[
                ServiceParam("start_date_time", "开始时间", param_type="string"),
                ServiceParam("end_date_time", "结束时间", param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["text"] = DomainDef(
        domain="text",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="文本实体",
        services=[
            ServiceDef(name="set_value", description="设置文本", params=[
                ServiceParam("value", "文本", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["datetime"] = DomainDef(
        domain="datetime",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="日期时间实体",
        services=[
            ServiceDef(name="set_value", description="设置值", params=[
                ServiceParam("datetime", "日期时间", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["date"] = DomainDef(
        domain="date",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="日期实体",
        services=[
            ServiceDef(name="set_value", description="设置日期", params=[
                ServiceParam("date", "日期", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["time"] = DomainDef(
        domain="time",
        domain_type=TYPE_CONTROLLABLE,
        priority=PRIORITY_EXTENDED,
        description="时间实体",
        services=[
            ServiceDef(name="set_value", description="设置时间", params=[
                ServiceParam("time", "时间", required=True, param_type="string"),
            ]),
        ]
    )

    DOMAIN_REGISTRY["image"] = DomainDef(
        domain="image",
        domain_type=TYPE_READ_ONLY,
        priority=PRIORITY_SPECIALIZED,
        description="图像实体",
        services=[],
    )

    DOMAIN_REGISTRY["event"] = DomainDef(
        domain="event",
        domain_type=TYPE_READ_ONLY,
        priority=PRIORITY_EXTENDED,
        description="事件实体",
        services=[],
    )


_register_domains()



def get_domain(domain: str) -> Optional[DomainDef]:

    return DOMAIN_REGISTRY.get(domain)


def get_service(domain: str, service: str) -> Optional[ServiceDef]:

    domain_def = DOMAIN_REGISTRY.get(domain)
    if not domain_def:
        return None

    for svc in domain_def.services:
        if svc.name == service or service in svc.aliases:
            return svc
    return None


def get_expected_state(domain: str, service: str, before_state: str | None = None) -> str | None:
    service_def = get_service(domain, service)
    if service_def is None:
        return None
    if service_def.expected_state is not None:
        return service_def.expected_state
    if service_def.toggle_states is not None:
        first, second = service_def.toggle_states
        if before_state == first:
            return second
        if before_state == second:
            return first
    return None


def get_action_service(domain: str, action: str) -> str:
    domain_def = DOMAIN_REGISTRY.get(domain)
    if domain_def is None:
        return action
    return domain_def.action_services.get(action, action)


_COLOR_ZH_TO_EN: Dict[str, str] = {
    "白": "white", "白色": "white", "暖白": "warm_white", "冷白": "cold_white",
    "红": "red", "红色": "red", "绿": "green", "绿色": "green",
    "蓝": "blue", "蓝色": "blue", "黄": "yellow", "黄色": "yellow",
    "紫": "purple", "紫色": "purple", "粉": "pink", "粉色": "pink",
    "橙": "orange", "橙色": "orange", "青": "cyan", "青色": "cyan",
    "品红": "magenta", "洋红": "magenta",
    "金": "gold", "金色": "gold", "银": "silver", "银色": "silver",
    "棕": "brown", "棕色": "brown", "灰": "gray", "灰色": "gray",
    "米": "wheat", "米色": "wheat", "米白": "linen",
    "天蓝": "skyblue", "深蓝": "navy", "浅蓝": "lightblue",
    "深红": "darkred", "浅红": "lightcoral", "玫红": "hotpink",
    "深绿": "darkgreen", "浅绿": "lightgreen", "草绿": "lawngreen",
    "淡黄": "lightyellow", "深黄": "goldenrod",
    "珊瑚": "coral", "珊瑚色": "coral",
    "象牙": "ivory", "象牙白": "ivory",
    "薰衣草": "lavender", "薰衣草色": "lavender",
    "桃": "peachpuff", "桃色": "peachpuff",
    "酒红": "maroon", "酒红色": "maroon",
    "翠绿": "springgreen", "荧光绿": "chartreuse",
    "靛": "indigo", "靛色": "indigo", "靛蓝": "indigo",
}

_COLOR_NAME_TO_TEMP: Dict[str, int] = {
    "white": 4000, "warm_white": 3000, "cold_white": 6000,
    "daylight": 5500, "warm": 2700, "cool": 6500,
    "natural": 4500, "neutral": 4000,
    "candlelight": 2200, "candle": 2200,
    "moonlight": 4100, "moon": 4100,
    "sunrise": 2700, "sunset": 2500,
    "reading": 5000,
}

_COLOR_NAME_TO_RGB: Dict[str, List[int]] = {
    "gold": [255, 215, 0], "silver": [192, 192, 192],
    "brown": [139, 69, 19], "gray": [128, 128, 128], "grey": [128, 128, 128],
    "wheat": [245, 222, 179], "linen": [250, 240, 230],
    "skyblue": [135, 206, 235], "navy": [0, 0, 128], "lightblue": [173, 216, 230],
    "darkred": [139, 0, 0], "lightcoral": [240, 128, 128], "hotpink": [255, 105, 180],
    "darkgreen": [0, 100, 0], "lightgreen": [144, 238, 144], "lawngreen": [124, 252, 0],
    "lightyellow": [255, 255, 224], "goldenrod": [218, 165, 32],
    "coral": [255, 127, 80], "ivory": [255, 255, 240],
    "lavender": [230, 230, 250], "peachpuff": [255, 218, 185],
    "maroon": [128, 0, 0], "springgreen": [0, 255, 127],
    "chartreuse": [127, 255, 0], "indigo": [75, 0, 130],
}

_KEY_ALIASES: Dict[str, Dict[str, str]] = {
    "light": {
        "color": "color_name", "colour": "color_name", "颜色": "color_name",
        "亮度": "brightness_pct", "明暗": "brightness_pct",
        "色温": "color_temp_kelvin", "色调": "hs_color",
        "过渡": "transition", "效果": "effect",
        "brightness_percent": "brightness_pct",
        "temp": "color_temp_kelvin", "kelvin": "color_temp_kelvin",
        "rgb": "rgb_color", "hs": "hs_color",
    },
    "climate": {
        "温度": "temperature", "目标温度": "temperature",
        "模式": "hvac_mode", "风速": "fan_mode",
        "temp": "temperature", "mode": "hvac_mode",
        "湿度": "humidity", "target_humidity": "humidity",
        "预设": "preset_mode", "preset": "preset_mode",
        "摆风": "swing_mode", "swing": "swing_mode",
    },
    "fan": {
        "速度": "percentage", "风速": "percentage",
        "speed": "percentage", "percent": "percentage",
        "preset": "preset_mode", "模式": "preset_mode",
        "方向": "direction", "direction": "direction",
        "摇头": "oscillating", "oscillate": "oscillating",
    },
    "cover": {
        "位置": "position", "pos": "position",
        "倾斜": "tilt_position", "tilt": "tilt_position",
    },
    "media_player": {
        "音量": "volume_level", "volume": "volume_level",
        "源": "source", "source": "source", "输入源": "source",
        "频道": "media_content_id", "channel": "media_content_id",
    },
    "humidifier": {
        "湿度": "humidity", "目标湿度": "humidity",
        "模式": "mode", "mode": "mode",
    },
    "vacuum": {
        "吸力": "fan_speed", "档位": "fan_speed", "speed": "fan_speed",
        "命令": "command", "cmd": "command",
    },
    "alarm_control_panel": {
        "密码": "code", "pin": "code", "password": "code",
    },
    "water_heater": {
        "温度": "temperature", "temp": "temperature",
        "模式": "operation_mode", "mode": "operation_mode",
    },
    "siren": {
        "音量": "volume_level", "volume": "volume_level",
        "音调": "tone", "声音": "tone",
        "时长": "duration", "持续": "duration",
    },
    "timer": {
        "时长": "duration", "时间": "duration",
    },
    "todo": {
        "内容": "item", "任务": "item", "task": "item",
        "截止": "due_date", "due": "due_date",
    },
    "calendar": {
        "标题": "summary", "title": "summary",
        "开始": "start_date_time", "start": "start_date_time",
        "结束": "end_date_time", "end": "end_date_time",
        "地点": "location", "place": "location",
    },
    "remote": {
        "命令": "command", "cmd": "command",
        "设备": "device", "次数": "num_repeats",
    },
    "valve": {
        "位置": "position", "pos": "position",
    },
}

_CLIMATE_MODE_ZH: Dict[str, str] = {
    "制冷": "cool", "冷气": "cool", "冷": "cool", "降温": "cool",
    "制热": "heat", "暖气": "heat", "热": "heat", "加热": "heat", "升温": "heat",
    "自动": "auto", "智能": "auto",
    "除湿": "dry", "抽湿": "dry", "干燥": "dry",
    "送风": "fan_only", "通风": "fan_only", "风扇": "fan_only",
    "关闭": "off", "关": "off", "停": "off",
    "节能": "eco", "省电": "eco",
    "舒适": "comfort", "睡眠": "sleep",
}

_FAN_MODE_ZH: Dict[str, str] = {
    "低": "low", "低速": "low", "小": "low", "弱": "low", "微风": "low",
    "中": "medium", "中速": "medium", "中等": "medium",
    "高": "high", "高速": "high", "大": "high", "强": "high", "强风": "high",
    "自动": "auto", "智能": "auto",
    "静音": "silent", "安静": "silent",
    "强力": "turbo", "最大": "turbo",
}

_SERVICE_ALIAS_ZH: Dict[str, List[str]] = {
    "turn_on": ["打开", "开", "开启", "启动", "亮", "开灯", "启用", "激活"],
    "turn_off": ["关闭", "关", "关掉", "熄灭", "灭", "关灯", "停止", "禁用"],
    "toggle": ["切换", "反转", "翻转"],
    "start": ["启动", "开始", "运行", "清扫", "开始清扫"],
    "stop": ["停止", "停", "暂停"],
    "pause": ["暂停", "休息"],
    "return_to_base": ["回充", "回家", "返回", "回去", "返回基座", "回充电座"],
    "lock": ["锁", "上锁", "锁门", "锁上"],
    "unlock": ["解锁", "开锁", "开门"],
    "open_cover": ["打开", "开", "升起", "拉开"],
    "close_cover": ["关闭", "关", "放下", "拉上", "合上"],
    "set_temperature": ["设温", "调温", "温度设为", "温度调到", "设置温度"],
    "set_hvac_mode": ["模式", "切换模式", "设置模式"],
    "locate": ["定位", "找", "响铃", "发声"],
    "set_volume_level": ["音量", "调音量", "声音"],
    "media_play": ["播放", "继续播放", "继续"],
    "media_pause": ["暂停", "暂停播放"],
    "media_next_track": ["下一首", "下一曲", "下一个"],
    "media_previous_track": ["上一首", "上一曲", "上一个"],
    "press": ["按", "按下", "点击", "触发"],
    "alarm_disarm": ["撤防", "解除警报", "关闭警报"],
    "alarm_arm_home": ["在家布防", "家庭布防"],
    "alarm_arm_away": ["离家布防", "外出布防"],
    "alarm_arm_night": ["夜间布防", "晚上布防", "睡眠布防"],
    "alarm_trigger": ["触发警报", "拉响警报"],
    "open_valve": ["打开阀门", "开阀"],
    "close_valve": ["关闭阀门", "关阀"],
    "start_mowing": ["割草", "开始割草", "除草"],
    "dock": ["回充", "返回基座", "回家"],
    "install": ["安装", "更新", "升级"],
    "add_item": ["添加", "新增", "加"],
    "remove_item": ["删除", "移除", "去掉"],
    "create_event": ["创建事件", "新建事件", "添加日程"],
    "send_command": ["发送命令", "调用", "控制"],
    "enable_motion_detection": ["开启侦测", "启用移动侦测"],
    "disable_motion_detection": ["关闭侦测", "禁用移动侦测"],
    "snapshot": ["拍照", "截图", "抓拍"],
    "record": ["录像", "录制", "开始录像"],
    "set_value": ["设置", "设为", "调为"],
    "increment": ["增加", "加1", "+1"],
    "decrement": ["减少", "减1", "-1"],
    "reset": ["重置", "清零"],
    "select_option": ["选择", "选"],
    "select_next": ["下一个"],
    "select_previous": ["上一个"],
    "reload": ["重新加载", "刷新"],
    "trigger": ["触发", "执行"],
    "oscillate": ["摆头", "摇头", "转头"],
    "set_percentage": ["设置风速", "调风速"],
    "volume_set": ["设置音量", "调音量"],
    "volume_up": ["音量+", "加大音量", "声音大一点"],
    "volume_down": ["音量-", "减小音量", "声音小一点"],
    "volume_mute": ["静音", "消音"],
    "set_humidity": ["设置湿度", "调湿", "湿度设为"],
    "set_fan_mode": ["设置风速", "调风速", "风速"],
    "set_fan_speed": ["设置吸力", "调吸力", "吸力"],
    "play_media": ["播放媒体", "播放音乐", "放歌"],
}

import re as _re

_NUM_RE = _re.compile(r"^[+-]?\d+(?:\.\d+)?")
_PCT_RE = _re.compile(r"^(\d+(?:\.\d+)?)\s*[%％]$")
_TEMP_RE = _re.compile(r"^(\d+(?:\.\d+)?)\s*[度℃°]?[cCfF]?$")


def _parse_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _NUM_RE.match(value.strip())
        if m:
            return float(m.group())
    return None


def _parse_pct(value: Any) -> Optional[float]:
    if isinstance(value, str):
        m = _PCT_RE.match(value.strip())
        if m:
            return float(m.group(1))
    return None


def _is_rgb_list(value: Any) -> bool:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return all(isinstance(v, (int, float)) and 0 <= v <= 255 for v in value)
    return False


def _is_hs_list(value: Any) -> bool:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return all(isinstance(v, (int, float)) for v in value)
    return False


_DOMAIN_DEFAULT_SERVICE: Dict[str, str] = {
    "light": "turn_on", "switch": "turn_on", "fan": "turn_on",
    "climate": "turn_on", "humidifier": "turn_on", "water_heater": "turn_on",
    "media_player": "media_play", "remote": "turn_on", "siren": "turn_on",
    "vacuum": "start", "lawn_mower": "start_mowing",
    "cover": "open_cover", "valve": "open_valve",
    "lock": "unlock", "button": "press", "scene": "turn_on",
    "automation": "trigger", "script": "turn_on",
    "timer": "start", "counter": "increment",
    "todo": "add_item", "calendar": "create_event",
    "input_boolean": "turn_on", "input_number": "set_value",
    "input_select": "select_option", "input_text": "set_value",
    "number": "set_value", "select": "select_option", "text": "set_value",
    "update": "install",
}


def fuzzy_resolve_service(domain: str, user_text: str) -> Optional[str]:
    text = user_text.strip().lower()
    domain_def = DOMAIN_REGISTRY.get(domain)
    if domain_def is None:
        return None
    available = {s.name for s in domain_def.services}
    if text in available:
        return text
    for svc_name, aliases in _SERVICE_ALIAS_ZH.items():
        real = domain_def.action_services.get(svc_name, svc_name)
        if real in available:
            for alias in aliases:
                if alias in text or text in alias:
                    return real
    for svc in domain_def.services:
        if svc.name in text:
            return svc.name
        for a in svc.aliases:
            if a in text:
                return svc.name
        if svc.description and svc.description in text:
            return svc.name
    default = _DOMAIN_DEFAULT_SERVICE.get(domain)
    if default and default in available:
        return default
    return domain_def.services[0].name if domain_def.services else None


def normalize_service_data(domain: str, service: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    aliases = _KEY_ALIASES.get(domain, {})
    normalized: Dict[str, Any] = {}
    for key, value in data.items():
        k = str(key).strip() if isinstance(key, str) else key
        canonical_key = aliases.get(k, k)
        normalized[canonical_key] = value

    if domain == "light" and service in ("turn_on", "toggle"):
        color_val = normalized.get("color_name")
        if isinstance(color_val, str):
            color_lower = color_val.strip().lower()
            en = _COLOR_ZH_TO_EN.get(color_lower, color_lower)
            if en in _COLOR_NAME_TO_TEMP:
                normalized.pop("color_name", None)
                normalized.setdefault("color_temp_kelvin", _COLOR_NAME_TO_TEMP[en])
            elif en in _COLOR_NAME_TO_RGB:
                normalized.pop("color_name", None)
                normalized.setdefault("rgb_color", _COLOR_NAME_TO_RGB[en])
            else:
                normalized["color_name"] = en
        elif _is_rgb_list(color_val):
            normalized.pop("color_name", None)
            normalized.setdefault("rgb_color", list(color_val))

        for k in ("color_temp_kelvin", "color_temp"):
            v = normalized.get(k)
            if isinstance(v, str):
                n = _parse_number(v)
                if n is not None:
                    normalized[k] = int(n)

        rgb_val = normalized.get("rgb_color")
        if isinstance(rgb_val, str):
            parts = _re.findall(r"\d+", rgb_val)
            if len(parts) == 3:
                normalized["rgb_color"] = [int(x) for x in parts]

        if "brightness_pct" in normalized and "brightness" not in normalized:
            pct_raw = normalized.pop("brightness_pct")
            pct = _parse_pct(pct_raw) if isinstance(pct_raw, str) else _parse_number(pct_raw)
            if pct is not None:
                normalized["brightness"] = max(0, min(255, int(float(pct) * 255 / 100)))
        elif "brightness" in normalized:
            b = normalized["brightness"]
            if isinstance(b, str):
                pct = _parse_pct(b)
                if pct is not None:
                    normalized["brightness"] = max(0, min(255, int(pct * 255 / 100)))
                else:
                    n = _parse_number(b)
                    if n is not None:
                        if n <= 1.0:
                            normalized["brightness"] = max(0, min(255, int(n * 255)))
                        elif n <= 100:
                            normalized["brightness"] = max(0, min(255, int(n * 255 / 100)))
                        else:
                            normalized["brightness"] = max(0, min(255, int(n)))

        if "transition" in normalized:
            t = normalized["transition"]
            n = _parse_number(t)
            if n is not None:
                normalized["transition"] = n

    if domain == "climate":
        for mode_key in ("hvac_mode", "preset_mode"):
            v = normalized.get(mode_key)
            if isinstance(v, str):
                mapped = _CLIMATE_MODE_ZH.get(v.strip(), v.strip().lower())
                normalized[mode_key] = mapped
        v = normalized.get("fan_mode")
        if isinstance(v, str):
            mapped = _FAN_MODE_ZH.get(v.strip(), v.strip().lower())
            normalized["fan_mode"] = mapped
        for temp_key in ("temperature", "target_temp_high", "target_temp_low"):
            v = normalized.get(temp_key)
            if isinstance(v, str):
                n = _parse_number(v)
                if n is not None:
                    normalized[temp_key] = n

    if domain == "fan":
        v = normalized.get("percentage")
        if isinstance(v, str):
            pct = _parse_pct(v)
            if pct is not None:
                normalized["percentage"] = int(pct)
            else:
                n = _parse_number(v)
                if n is not None:
                    normalized["percentage"] = int(n) if n > 1 else int(n * 100)
        v = normalized.get("preset_mode")
        if isinstance(v, str):
            mapped = _FAN_MODE_ZH.get(v.strip(), v.strip().lower())
            normalized["preset_mode"] = mapped
        v = normalized.get("oscillating")
        if isinstance(v, str):
            normalized["oscillating"] = v.strip().lower() in ("true", "1", "on", "是", "开")

    if domain == "cover":
        for pk in ("position", "tilt_position"):
            v = normalized.get(pk)
            if isinstance(v, str):
                pct = _parse_pct(v)
                if pct is not None:
                    normalized[pk] = int(pct)
                else:
                    n = _parse_number(v)
                    if n is not None:
                        normalized[pk] = max(0, min(100, int(n)))

    if domain == "media_player":
        v = normalized.get("volume_level")
        if v is not None:
            n = _parse_number(v)
            if n is not None:
                normalized["volume_level"] = n / 100.0 if n > 1.0 else n

    if domain == "humidifier":
        v = normalized.get("humidity")
        if v is not None:
            n = _parse_number(v)
            if n is not None:
                normalized["humidity"] = int(n)
        v = normalized.get("mode")
        if isinstance(v, str):
            mapped = _CLIMATE_MODE_ZH.get(v.strip(), v.strip().lower())
            normalized["mode"] = mapped

    return normalized


def validate_service_call(domain: str, service: str, data: Dict[str, Any] = None) -> Dict[str, Any]:

    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "normalized_service": service,
        "suggestions": {},
    }

    domain_def = DOMAIN_REGISTRY.get(domain)
    if not domain_def:
        result["warnings"].append(f"域 '{domain}' 未在注册表中，无法验证")
        return result

    service_def = get_service(domain, service)
    if not service_def:
        available = [s.name for s in domain_def.services]
        result["errors"].append(f"域 '{domain}' 不支持服务 '{service}'，可用: {available}")
        result["valid"] = False
        return result

    result["normalized_service"] = service_def.name

    if not data:
        data = {}

    for param in service_def.params:
        if param.required and param.name not in data:
            result["errors"].append(f"缺少必需参数: {param.name} ({param.description})")
            result["valid"] = False

    for param in service_def.params:
        if param.name not in data:
            continue

        value = data[param.name]

        if param.enum and value not in param.enum:
            result["errors"].append(f"参数 '{param.name}' 值 '{value}' 无效，可选: {param.enum}")
            result["valid"] = False

        if param.param_type == "number" and isinstance(value, (int, float)):
            if param.min_value is not None and value < param.min_value:
                result["errors"].append(f"参数 '{param.name}' 值 {value} 小于最小值 {param.min_value}")
                result["valid"] = False
            if param.max_value is not None and value > param.max_value:
                result["errors"].append(f"参数 '{param.name}' 值 {value} 大于最大值 {param.max_value}")
                result["valid"] = False

    for param in service_def.params:
        if param.name not in data:
            suggestion = {"description": param.description, "type": param.param_type}
            if param.default is not None:
                suggestion["default"] = param.default
            if param.enum:
                suggestion["options"] = param.enum
            if param.min_value is not None:
                suggestion["min"] = param.min_value
            if param.max_value is not None:
                suggestion["max"] = param.max_value
            result["suggestions"][param.name] = suggestion

    return result


def get_service_help(domain: str, service: str = None) -> str:

    domain_def = DOMAIN_REGISTRY.get(domain)
    if not domain_def:
        return f"未知域: {domain}"

    lines = [f"## {domain} ({domain_def.description})"]
    lines.append(f"类型: {domain_def.domain_type}")

    if service:
        service_def = get_service(domain, service)
        if not service_def:
            return f"未知服务: {domain}.{service}"

        lines.append(f"\n### {service_def.name}")
        lines.append(f"描述: {service_def.description}")
        if service_def.aliases:
            lines.append(f"别名: {', '.join(service_def.aliases)}")
        if service_def.params:
            lines.append("\n参数:")
            for p in service_def.params:
                req = "必需" if p.required else "可选"
                line = f"  - {p.name} ({p.param_type}, {req}): {p.description}"
                if p.enum:
                    line += f" [可选值: {', '.join(str(e) for e in p.enum)}]"
                if p.min_value is not None or p.max_value is not None:
                    line += f" [范围: {p.min_value}-{p.max_value}]"
                lines.append(line)
    else:
        lines.append("\n可用服务:")
        for svc in domain_def.services:
            aliases = f" (别名: {', '.join(svc.aliases)})" if svc.aliases else ""
            lines.append(f"  - {svc.name}: {svc.description}{aliases}")

    return "\n".join(lines)
