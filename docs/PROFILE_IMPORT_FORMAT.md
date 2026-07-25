# 프로필 임포트 형식 v1

GPT 대화에서 얻은 자기 이해를 Claude 쪽 프로필 DB로 옮기는 단방향 경로.

실시간 연동이 아니다. 사용자가 GPT에게 내보내기를 시키고, 결과 파일을 임포트한다.
ChatGPT Free 플랜에서는 커스텀 MCP·Actions가 모두 막혀 있어 이 방식이 유일한 경로다.
(유료 전환 시 실시간 연동 설계: [REMOTE_GPT_INTEGRATION.md](REMOTE_GPT_INTEGRATION.md))

---

## 1. 파일 형식

`profile-import-<날짜>.json`

```json
{
  "format": "career-profile-import/v1",
  "exported_at": "2026-07-25T14:00:00+09:00",
  "source": "gpt_import",
  "facts": [
    {
      "kind": "strength",
      "content": "복잡한 기술 개념을 비전공자에게 풀어 설명하는 데 능숙하다",
      "evidence": "동아리에서 신입 대상 Flutter 입문 세션을 3회 진행했고, 매회 피드백에서 설명이 이해하기 쉬웠다는 응답이 다수였다",
      "tags": ["communication", "teaching"],
      "confidence": 0.8
    },
    {
      "kind": "weakness",
      "content": "REST API 설계 경험이 얕다",
      "evidence": "API를 소비하는 클라이언트만 만들어봤고, 엔드포인트 구조나 버저닝을 직접 설계한 적이 없다",
      "tags": ["backend"],
      "confidence": 0.9
    }
  ]
}
```

### 필드

| 필드 | 필수 | 설명 |
|---|---|---|
| `kind` | ✅ | `strength` \| `weakness` \| `skill` \| `experience` \| `preference` \| `goal` |
| `content` | ✅ | 한 문장으로 된 **하나의** 사실. 여러 개를 묶지 않는다 |
| `evidence` | 권장 | 그렇게 판단한 **구체적 근거**. 아래 참조 |
| `tags` | | 검색·분류용 짧은 키워드 |
| `confidence` | | 0.0~1.0. 생략 시 0.7 |

### `evidence`가 중요한 이유

매칭 결과는 이런 형태로 나온다.

```json
{"jd_req": "Flutter 앱 개발 경험", "evidence_fact_id": 41}
```

여기서 참조되는 Fact에 근거가 없으면 **"왜 맞다고 보는지"를 설명할 수 없다.**
`content`가 주장이라면 `evidence`는 그 주장이 자소서에서 버틸 수 있게 하는 재료다.
근거 없는 강점은 매칭 점수는 올리지만 지원서에는 쓸 수 없다.

## 2. 규칙

**한 항목 = 한 사실.** "커뮤니케이션이 좋고 리더십도 있다"는 두 개로 나눈다. 나중에 하나만 대체하거나 반박할 수 있어야 한다.

**중복은 자동으로 걸러진다.** `kind + content`(공백·대소문자 정규화)의 SHA-256 해시로 판정한다. 같은 파일을 두 번 넣어도 안전하고, 매번 전체를 다시 내보내도 새 사실만 들어간다. **증분만 골라낼 필요가 없다.**

**기존 사실의 수정은 임포트로 하지 않는다.** 임포트는 추가 전용이다. 내용이 바뀌었으면 Claude에서 `profile_revise`로 대체한다 — 그래야 이력이 남는다.

**모든 임포트 항목은 `source = "gpt_import"`로 기록된다.** Claude에서 쌓인 것과 구분되어 `profile_diff`로 조회된다.

## 3. GPT에게 시킬 프롬프트

대화 말미에 아래를 붙여넣는다.

```
지금까지 우리 대화에서 드러난 나에 대한 사실들을 아래 JSON 형식으로 정리해줘.

{
  "format": "career-profile-import/v1",
  "exported_at": "<현재 시각 ISO8601>",
  "source": "gpt_import",
  "facts": [
    {
      "kind": "strength|weakness|skill|experience|preference|goal 중 하나",
      "content": "한 문장으로 된 하나의 사실",
      "evidence": "그렇게 판단한 구체적 근거 (대화에서 실제로 나온 사례)",
      "tags": ["짧은", "키워드"],
      "confidence": 0.0~1.0
    }
  ]
}

규칙:
- 한 항목에 하나의 사실만. "A이고 B도 하다"는 두 개로 나눠라.
- evidence 는 반드시 우리 대화에서 실제로 나온 구체적 사례여야 한다.
  대화에 근거가 없으면 그 항목은 아예 넣지 마라. 지어내지 마라.
- 추측이나 일반론은 제외한다. 내가 직접 말한 것과 그로부터 명확히
  따라 나오는 것만 넣어라.
- confidence: 내가 명시적으로 말한 것은 0.9, 대화에서 추론한 것은 0.6 정도.
- 중복 걱정은 하지 마라. 이미 저장된 것은 자동으로 걸러진다.
  매번 전체를 다시 내보내도 된다.

JSON만 출력하고 다른 설명은 붙이지 마라.
```

**"지어내지 마라"와 "근거 없으면 빼라"가 이 프롬프트의 핵심이다.** 모델은 요약을 요청받으면 그럴듯한 강점을 채워 넣는 경향이 있고, 그렇게 들어온 가짜 사실은 나중에 매칭 근거로 인용되면서 자소서까지 오염시킨다.

## 4. 임포트

Claude 대화에서:

```
profile-import-2026-07-25.json 임포트해줘
```

`profile_import` 툴이 하는 일:

1. 형식 검증 (`format` 필드 확인, 알 수 없는 버전은 거부)
2. 각 항목을 `Fact`로 변환 — 잘못된 `kind`나 빈 `content`는 건너뛰고 사유를 보고
3. 활성 Fact와 해시 대조 → 중복 제외
4. 신규만 저장
5. **결과를 사용자에게 요약해 보여준다**

```
임포트 완료: 신규 7건, 중복 12건, 오류 1건
  신규 strength 3, weakness 2, skill 2
  오류: facts[14] — kind "motivation" 은 허용되지 않음
```

조용히 저장하지 않는다. 무엇이 들어갔는지 사용자가 확인할 수 있어야 신뢰가 유지된다.

## 5. 버저닝

`format` 필드로 판별한다. 알 수 없는 버전은 **거부하고 이유를 말한다.** 추측해서 읽지 않는다 — 잘못 해석된 프로필은 조용히 매칭 품질을 떨어뜨리고, 원인 추적이 어렵다.
