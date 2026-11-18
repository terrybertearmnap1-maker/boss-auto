"""LangGraph 求职决策流程 —— 状态定义。

一次「岗位评估」就是一张图的执行：JD 文本进，决策 + 打招呼语出。
"""

from typing import Dict, List, TypedDict


class JobState(TypedDict, total=False):
    # ---- 输入 ----
    title: str
    company: str
    salary: str
    jd_text: str
    threshold: int
    profile: Dict[str, List[str]]     # 技能画像（core / bonus / exclude）

    # ---- 中间产物 ----
    sections: Dict[str, str]          # 拆出来的「岗位职责」「任职要求」
    jd_skills: List[str]              # JD 里出现的技能（用于解释为什么匹配/不匹配）
    matched: List[str]                # 我命中 JD 的技能
    missing: List[str]                # JD 要求但我没有的技能
    banned: str                       # 命中的排除词
    score: int                        # 0-100

    # ---- 决策 ----
    decision: str                     # apply / skip
    reason: str
    greeting: str

    # ---- 可观测性 ----
    trace: List[str]                  # 每个节点追加一行，便于回放与调试
