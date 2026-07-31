from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OCRBlock:
    x1: float
    y1: float
    x2: float
    y2: float
    text: str
    confidence: float
    pass_label: str = "base"

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TableRegion:
    region_id: str
    page: int
    x1: float
    y1: float
    x2: float
    y2: float
    split_reason: str
    block_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Cell:
    row: int
    col: int
    x1: float
    y1: float
    x2: float
    y2: float
    texts: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def add_text(self, text: str, confidence: float) -> None:
        cleaned = text.strip()
        if cleaned:
            self.texts.append(cleaned)
            self.confidence = max(self.confidence, confidence)

    @property
    def text(self) -> str:
        parts: list[str] = []
        for part in self.texts:
            if not parts or parts[-1] != part:
                parts.append(part)
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["text"] = self.text
        return payload


@dataclass
class QualityIssue:
    severity: str
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
