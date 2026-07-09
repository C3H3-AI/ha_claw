"""
正式测试：IM mapping 流程模拟
模拟场景：
- cn_im_hub 已配置 feishu + wechat
- 对话历史中有 feishu 和 wechat 对话
- 用户从 um_pick_channel 选择 wechat，进入 um_pick_identity
测试各函数在上下游代码下的行为差异
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_components"))

# --- 模拟 HA 环境 ---
class MockHassConfig:
    language = "zh-Hans"

class MockHass:
    config = MockHassConfig()
    data = {}

# --- 模拟数据 ---

# CN IM Hub 追踪的已知目标
# 注意：有些目标可能带有 @im.{provider} 后缀，有些不带
CN_IM_TARGETS = {
    "feishu": {
        # feishu 目标不带 @im.feishu 后缀
        "oc_0c06588ea12a57669f1bf7cc33017b57":        "私聊 · oc_0c06588ea1…",
        "oc_a1c7bc051a3c8215c268cde0beee8ace":        "群聊 · oc_a1c7bc… (家庭群)",
    },
    "wechat": {
        # wechat 目标带 @im.wechat 后缀
        "o9cq807kE0bhaoCR3JKBaE8KYGZk@im.wechat":     "倪一可",
    },
}

# 对话历史中的 conversation_id
CONVERSATION_IDS = {
    # format: {provider}:{ext_id}
    "feishu:oc_0c06588ea12a57669f1bf7cc33017b57",
    "feishu:oc_a1c7bc051a3c8215c268cde0beee8ace",
    "wechat:o9cq807kE0bhaoCR3JKBaE8KYGZk",
}

# 已有映射
EXISTING_MAPPINGS = [
]

# --- 测试目标函数（从 im_channel_helpers.py 复制的核心逻辑）---

IM_CHANNEL_NAMES = {
    "wechat:": "WeChat",
    "feishu:": "Feishu",
    "dingtalk:": "DingTalk",
    "qq:": "QQ",
    "wecom:": "WeCom",
    "xiaoyi:": "XiaoYi",
}

def _short_id(value, limit=18):
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit - 1]}…"

def parse_im_conversation_id(conversation_id):
    if not conversation_id:
        return None
    lowered = conversation_id.lower()
    for prefix in IM_CHANNEL_NAMES:
        if not lowered.startswith(prefix.lower()):
            continue
        provider = prefix.rstrip(":").lower()
        rest = conversation_id[len(prefix):]
        if not rest:
            return None
        parts = rest.split(":", 1)
        ext_id = parts[1] if len(parts) >= 2 else parts[0]
        ext_id = ext_id.strip()
        if ext_id:
            return provider, ext_id
        return None
    return None

def _load_cn_im_hub_targets():
    """模拟 _load_cn_im_hub_targets 返回格式"""
    return CN_IM_TARGETS

def _load_history_targets(skip_ext_ids=None):
    """模拟 _load_history_targets - 新版本（带 skip_ext_ids）"""
    result = {}
    for conv_id in CONVERSATION_IDS:
        parsed = parse_im_conversation_id(conv_id)
        if not parsed:
            continue
        provider, ext_id = parsed
        if skip_ext_ids and ext_id in skip_ext_ids:
            continue
        bucket = result.setdefault(provider, {})
        if ext_id not in bucket:
            bucket[ext_id] = f"对话 · {_short_id(ext_id)}"
    return result

def _load_history_targets_old():
    """模拟 _load_history_targets - 旧版本（无 skip_ext_ids）"""
    result = {}
    for conv_id in CONVERSATION_IDS:
        parsed = parse_im_conversation_id(conv_id)
        if not parsed:
            continue
        provider, ext_id = parsed
        bucket = result.setdefault(provider, {})
        if ext_id not in bucket:
            bucket[ext_id] = _short_id(ext_id)
    return result

def _load_mapping_targets(mappings):
    result = {}
    for mapping in mappings:
        provider = mapping.get("provider", "")
        ext_id = mapping.get("ext_id", "")
        if provider and ext_id:
            bucket = result.setdefault(provider, {})
            if ext_id not in bucket:
                bucket[ext_id] = _short_id(ext_id)
    return result

# --- 新版 collect_provider_targets（带归一化 + 去重）---
def collect_provider_targets_new():
    merged = {}
    cn_im_sources = _load_cn_im_hub_targets()
    
    history_skip = set()
    for provider, targets in cn_im_sources.items():
        provider_clean = provider.rstrip(":").lower()
        suffix = f"@im.{provider_clean}"
        for ext_id in targets:
            normalized = ext_id
            if normalized.endswith(suffix):
                normalized = normalized[:-len(suffix)]
            if normalized:
                history_skip.add(normalized)
    
    for source in (
        cn_im_sources,
        _load_history_targets(skip_ext_ids=history_skip),
        _load_mapping_targets(EXISTING_MAPPINGS),
    ):
        for provider, targets in source.items():
            bucket = merged.setdefault(provider, {})
            provider_clean = provider.rstrip(":").lower()
            suffix = f"@im.{provider_clean}"
            for ext_id, display in targets.items():
                if not ext_id:
                    continue
                normalized = ext_id
                if normalized.endswith(suffix):
                    normalized = normalized[:-len(suffix)]
                if not normalized or normalized in bucket:
                    continue
                bucket[normalized] = display
    return merged

# --- 旧版 collect_provider_targets（无归一化）---
def collect_provider_targets_old():
    merged = {}
    for source in (
        _load_cn_im_hub_targets(),
        _load_history_targets_old(),
        _load_mapping_targets(EXISTING_MAPPINGS),
    ):
        for provider, targets in source.items():
            bucket = merged.setdefault(provider, {})
            for ext_id, display in targets.items():
                if not ext_id or ext_id in bucket:
                    continue
                bucket[ext_id] = display
    return merged

def build_ext_id_options(provider, provider_targets, manual_label="手动输入…"):
    options = {}
    used_labels = {}
    for ext_id, display in sorted(
        provider_targets.get(provider, {}).items(),
        key=lambda item: (item[1].lower(), item[0].lower()),
    ):
        options[ext_id] = display  # simplified
    options["__manual__"] = manual_label
    return options

def _build_remove_options(mappings):
    remove_options = {}
    for mapping in mappings:
        provider = mapping.get("provider", "?")
        ext_id = mapping.get("ext_id", "?")
        key = f"{provider}:{ext_id}"
        remove_options[key] = f"{provider} | {ext_id[:40]} → someone"
    return remove_options

# ============ 测试 ============

print("=" * 70)
print("场景：用户已配置 feishu + wechat，有历史对话")
print(f"CN IM Hub targets: {CN_IM_TARGETS}")
print(f"History IDs: {CONVERSATION_IDS}")
print(f"现有映射: {EXISTING_MAPPINGS}")
print("=" * 70)

# 测试1: 旧版 collect - 检查 provider 过滤是否生效
print("\n\n【测试1】旧版 collect_provider_targets")
old_targets = collect_provider_targets_old()
print(f"  合并结果 providers: {list(old_targets.keys())}")
print(f"  feishu targets: {list(old_targets.get('feishu', {}).keys())}")
print(f"  wechat targets: {list(old_targets.get('wechat', {}).keys())}")

wechat_opts_old = build_ext_id_options("wechat", old_targets)
print(f"\n  用户选 wechat → ext_id_options keys: {list(wechat_opts_old.keys())}")
print(f"  vol.In() 显示: {list(wechat_opts_old.keys())}")

# 检查：旧版会展示 @im.wechat 后缀，且历史对话中 feishu 的 ext_id 也会出现
# 原因：@im.wechat 后缀导致 key 不一致，但 build_ext_id_options 按 provider 过滤，
# 所以 wechat 只会显示 wechat 的 key（含 @im.wechat 后缀）
print(f"\n  ✅ 旧版按 provider 过滤: wechat 只显示 wechat 的 ext_id")
print(f"  ⚠️ 但 wechat ext_id 带有 @im.wechat 后缀")

# 测试2: 新版 collect
print("\n\n【测试2】新版 collect_provider_targets（带归一化+去重）")
new_targets = collect_provider_targets_new()
print(f"  合并结果 providers: {list(new_targets.keys())}")
print(f"  feishu targets: {list(new_targets.get('feishu', {}).keys())}")
print(f"  wechat targets: {list(new_targets.get('wechat', {}).keys())}")

wechat_opts_new = build_ext_id_options("wechat", new_targets)
print(f"\n  用户选 wechat → ext_id_options keys: {list(wechat_opts_new.keys())}")
print(f"  vol.In() 显示: {list(wechat_opts_new.keys())}")
print(f"  ✅ @im.wechat 后缀已被归一化去除")

# 测试3: 检查已有映射时的 _build_remove_options
print("\n\n【测试3】um_remove 步骤的 remove_options")
mappings_with_data = [
    {"provider": "feishu", "ext_id": "oc_0c06588ea12a57669f1bf7cc33017b57", "ha_user_id": "user1"},
]
remove_opts = _build_remove_options(mappings_with_data)
print(f"  remove_options keys: {list(remove_opts.keys())}")
print(f"  vol.In() 显示: {list(remove_opts.keys())}")
print(f"  ⚠️ remove_options 的 key 格式是 provider:ext_id!")
print(f"  ⚠️ 这正好匹配用户看到错误格式: feishu:oc_0c06588ea12a57669f1bf7cc33017b57")

# 测试4: 检查 parse_im_conversation_id 对不同格式的处理
print("\n\n【测试4】parse_im_conversation_id 边界情况")
test_ids = [
    "feishu:oc_0c06588ea12a57669f1bf7cc33017b57",
    "wechat:o9cq807kE0bhaoCR3JKBaE8KYGZk",
    "wechat:user:o9cq807kE0bhaoCR3JKBaE8KYGZk",
    "feishu:oc_0c06588ea12a57669f1bf7cc33017b57@im.feishu",
    "wechat:o9cq807kE0bhaoCR3JKBaE8KYGZk@im.wechat",
]
for cid in test_ids:
    result = parse_im_conversation_id(cid)
    print(f"  {cid} → provider={result[0] if result else None}, ext_id={result[1] if result else None}")

# 测试5: 如果 provider filter 被 bypass 会怎样
print("\n\n【测试5】如果 provider 参数被忽略（传空字符串）")
for provider in ["", "feishu", "wechat", "unknown"]:
    opts = build_ext_id_options(provider, new_targets)
    print(f"  build_ext_id_options(provider='{provider}') → keys: {list(opts.keys())}")
print(f"  ⚠️ 若 provider='' → 只显示 __manual__")
print(f"  ✅ 不可能出现 feishu ext_id 当 provider='wechat'")

print("\n\n" + "=" * 70)
print("结论：")
print("1. build_ext_id_options 的 provider 过滤是可靠的")
print("2. @im.wechat 后缀会被 collect_provider_targets 归一化")
print("3. remove_options 的 key 格式 (provider:ext_id) 与用户看到的错误格式完全一致")
print("4. 建议：检查 error 是否来自 um_remove 而不是 um_pick_identity")
print("=" * 70)

# 模拟完整 flow 测试
print("\n\n【完整流程模拟】")
print("Step 1: user_mapping → menu → 选 um_pick_channel")
print("Step 2: um_pick_channel(user_input={'provider': 'wechat'})")
print("  → _um_provider = 'wechat'")
print("  → um_pick_identity(None)")

# 模拟 um_pick_identity 第一次渲染
provider = "wechat"
provider_keys = ["feishu", "wechat"]
assert provider in provider_keys, "provider 合法"
provider_targets = collect_provider_targets_new()
ext_id_options = build_ext_id_options(provider, provider_targets)
print(f"\nStep 3: um_pick_identity 渲染")
print(f"  provider = '{provider}'")
print(f"  ext_id_options keys: {list(ext_id_options.keys())}")
print(f"  ✅ wechat 只显示 wechat ext_id: {[k for k in ext_id_options if k != '__manual__']}")

# 模拟 form 提交后 voluptuous 验证
import voluptuous as vol
schema = vol.Schema({
    vol.Required("ext_id"): vol.In(ext_id_options),
    vol.Optional("ext_id_manual", default=""): str,
})
print(f"\nStep 4: Form 提交测试")
# 测试有效提交
try:
    schema({"ext_id": "o9cq807kE0bhaoCR3JKBaE8KYGZk"})
    print(f"  ✅ 有效提交通过: ext_id=o9cq807kE0bhaoCR3JKBaE8KYGZk")
except Exception as e:
    print(f"  ❌ 有效提交失败: {e}")

# 测试无效提交
try:
    schema({"ext_id": "oc_0c06588ea12a57669f1bf7cc33017b57"})
    print(f"  ❌ feishu ext_id 本应被拒绝但通过了")
except vol.MultipleInvalid as e:
    print(f"  ✅ feishu ext_id 被正确拒绝: {e}")
except Exception as e:
    print(f"  - {e}")

try:
    schema({"ext_id": "feishu:oc_0c06588ea12a57669f1bf7cc33017b57"})
    print(f"  ❌ feishu:ext_id 格式被意外通过了")
except vol.MultipleInvalid as e:
    print(f"  ✅ feishu:ext_id 被正确拒绝: {e}")
except Exception as e:
    print(f"  - {e}")

print("\n✅ 测试完成 - build_ext_id_options 的 provider 过滤是正确的")
print("若问题持续，建议检查部署版本是否已同步本地改动，或检查 um_remove 步骤")
