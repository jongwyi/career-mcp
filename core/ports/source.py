"""수집 소스 포트.

가져오기(fetch)와 해석하기(parse)를 분리한 것이 핵심이다.

- 공식 API / 워커 스크랩 소스는 둘 다 구현한다.
- 크롬 확장 소스는 **Parser 만** 구현한다. 가져오는 주체가 브라우저이지
  서버가 아니기 때문이다. 하나의 SourceAdapter 인터페이스로 묶었다면
  잡코리아 어댑터에 빈 fetch() 를 두는 어색한 코드가 나왔을 것이다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from core.domain.job import ParseResult, RawPosting


@runtime_checkable
class PostingParser(Protocol):
    """RawPosting → JobPosting. 순수 함수여야 한다(네트워크 금지).

    순수해야 저장된 raw 로 재처리가 가능하다.
    """

    source_id: str

    def parse(self, raw: RawPosting) -> ParseResult: ...


@runtime_checkable
class PostingFetcher(Protocol):
    """외부에서 원본을 가져온다. 워커에서만 호출된다.

    구현체는 adapters/sources/base.py 의 레이트리밋·robots 준수를 상속한다.
    """

    source_id: str

    def fetch(self, since: datetime | None = None) -> AsyncIterator[RawPosting]: ...
