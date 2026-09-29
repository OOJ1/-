"""答案文本美化：把常见 LaTeX 记号转成可读字符，避免答案里满屏反斜杠。

只处理高频记号，不追求完整 LaTeX 排版（Qt 不内置公式渲染）。
"""

from __future__ import annotations

import re

_SIMPLE = [
    ("\\times", "×"), ("\\div", "÷"), ("\\cdot", "·"), ("\\ast", "*"),
    ("\\leq", "≤"), ("\\le", "≤"), ("\\geq", "≥"), ("\\ge", "≥"),
    ("\\neq", "≠"), ("\\ne", "≠"), ("\\approx", "≈"), ("\\equiv", "≡"),
    ("\\pm", "±"), ("\\mp", "∓"), ("\\infty", "∞"), ("\\propto", "∝"),
    ("\\alpha", "α"), ("\\beta", "β"), ("\\gamma", "γ"), ("\\Gamma", "Γ"),
    ("\\delta", "δ"), ("\\Delta", "Δ"), ("\\epsilon", "ε"), ("\\varepsilon", "ε"),
    ("\\theta", "θ"), ("\\lambda", "λ"), ("\\mu", "μ"), ("\\nu", "ν"),
    ("\\pi", "π"), ("\\rho", "ρ"), ("\\sigma", "σ"), ("\\Sigma", "Σ"),
    ("\\tau", "τ"), ("\\phi", "φ"), ("\\varphi", "φ"), ("\\omega", "ω"), ("\\Omega", "Ω"),
    ("\\sum", "∑"), ("\\prod", "∏"), ("\\int", "∫"), ("\\partial", "∂"), ("\\nabla", "∇"),
    ("\\in", "∈"), ("\\notin", "∉"), ("\\subset", "⊂"), ("\\subseteq", "⊆"),
    ("\\cup", "∪"), ("\\cap", "∩"), ("\\emptyset", "∅"), ("\\forall", "∀"), ("\\exists", "∃"),
    ("\\rightarrow", "→"), ("\\to", "→"), ("\\Rightarrow", "⇒"), ("\\leftarrow", "←"),
    ("\\Leftrightarrow", "⇔"), ("\\leftrightarrow", "↔"),
    ("\\angle", "∠"), ("\\perp", "⊥"), ("\\parallel", "∥"), ("\\triangle", "△"),
    ("\\ldots", "…"), ("\\cdots", "…"), ("\\dots", "…"),
    ("\\quad", "  "), ("\\qquad", "    "), ("\\,", " "), ("\\;", " "), ("\\!", ""),
    ("\\left", ""), ("\\right", ""), ("\\displaystyle", ""), ("\\limits", ""),
    ("\\%", "%"), ("\\$", "$"), ("\\&", "&"), ("\\#", "#"), ("\\_", "_"),
    ("\\ ", " "),   # LaTeX 的"反斜杠+空格"也是空格
]

_FRAC = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_TEXT = re.compile(r"\\text(?:rm|bf|it)?\s*\{([^{}]*)\}")
_SUP = re.compile(r"\^\s*\{?([0-9]{1,2})\}?")
_SUB = re.compile(r"_\s*\{([^{}]*)\}")
_SUB_SIMPLE = re.compile(r"_([0-9])")  # x_1 这种不带花括号的写法
_SUP_TABLE = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_SUB_TABLE = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def beautify_latex(text: str) -> str:
    """把 LaTeX 记号折成可读字符，保留 $ 分隔符。"""
    if not text:
        return ""
    out = text
    # 嵌套分数/根号最多迭代 3 轮，够用且不会死循环
    for _ in range(3):
        new = _FRAC.sub(lambda m: f"({m.group(1)})/({m.group(2)})", out)
        new = _SQRT.sub(lambda m: f"√({m.group(1)})", new)
        if new == out:
            break
        out = new
    out = _TEXT.sub(lambda m: m.group(1), out)
    for src, dst in _SIMPLE:
        out = out.replace(src, dst)
    out = _SUP.sub(lambda m: m.group(1).translate(_SUP_TABLE), out)
    out = _SUB.sub(lambda m: m.group(1).translate(_SUB_TABLE), out)
    out = _SUB_SIMPLE.sub(lambda m: m.group(1).translate(_SUB_TABLE), out)
    # 花括号包裹的单层表达式 {x} → x
    out = re.sub(r"\{([^{}]{0,40})\}", r"\1", out)
    return out


def strip_math_delims(text: str) -> str:
    """去掉 $ / $$ 分隔符，纯文本阅读更清爽。"""
    if not text:
        return ""
    return text.replace("$$", "").replace("$", "")


def to_plain(text: str) -> str:
    return strip_math_delims(beautify_latex(text or ""))


def to_markdown(text: str) -> str:
    """用于 QTextDocument.setMarkdown 的预处理。"""
    return to_plain(text).strip()


def preview(text: str, limit: int = 60) -> str:
    """列表里显示的一句话摘要。"""
    s = " ".join((text or "").split())
    return s[:limit] + ("…" if len(s) > limit else "")
