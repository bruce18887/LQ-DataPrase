from .base import BaseATEParser, SYSTEM_COLUMNS
from .cta8290d import CTA8290DParser
from .cta8280f import CTA8280FParser
from .ets88 import ETS88Parser
from .sts8200 import STS8200Parser

PARSER_REGISTRY = {
    'CTA8290D': CTA8290DParser,
    'CTA8280F': CTA8280FParser,
    'ETS88': ETS88Parser,
    'STS8200': STS8200Parser,
}

def get_parser(format_type: str) -> BaseATEParser:
    parser_cls = PARSER_REGISTRY.get(format_type)
    if not parser_cls:
        raise ValueError(f"不支持的格式类型: {format_type}")
    return parser_cls()
