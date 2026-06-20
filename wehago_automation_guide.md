# WEHAGO 원천세 신고 Canvas 화면 AI/RPA 자동화 설계 정리

> **아카이브 안내 — 초기 설계 탐색 문서입니다.** 본 문서는 WEHAGO 원천세 화면이 `canvas` 기반이라는 **전제**로 작성되었으나,
> **실제 구현은 canvas가 아닌 DOM(LS_ngh_select2 / WSC_LUXButton) + COM UIAutomation 기반**입니다(`src/automation/wehago/`).
> 채택된 아키텍처는 **GUIDE.md**를 참조하세요. 본 문서는 설계 논의 기록으로만 활용합니다.

## 0. 문서 목적

이 문서는 더존 WEHAGO의 회계·세무 기장 관련 솔루션, 특히 **원천세 신고 페이지**처럼 입력 영역이 일반 HTML DOM 구조가 아니라 `canvas` 태그 기반으로 구성된 화면을 AI와 자동화 도구로 제어하기 위한 접근 방법을 정리한 것이다.

전제 조건은 다음과 같다.

- 사용자는 WEHAGO에 **사람이 직접 로그인**해둔다.
- 공식적으로 사용할 수 있는 오픈 API는 없다고 가정한다.
- 원천세 신고 화면의 입력 섹션은 일반적인 `input`, `textarea`, `select` DOM으로 노출되지 않고 `canvas`에 렌더링되어 있다고 가정한다.
- 자동화 목적은 회계·세무 업무의 반복 입력을 줄이고, 입력값 검증 및 임시저장 흐름을 보조하는 것이다.
- 최종 신고·제출 단계는 업무 리스크가 크므로 사람 승인 절차를 유지하는 것을 권장한다.

---

## 1. 핵심 결론

`canvas` 내부의 입력 필드는 DOM 요소가 아니므로 `document.querySelector()`, `locator('input')`, `element.value = ...` 같은 방식으로 직접 값을 넣을 수 없다.

따라서 자동화는 다음 방향으로 설계하는 것이 현실적이다.

```text
사람이 WEHAGO 로그인
        ↓
자동화 프로그램이 로그인된 브라우저 세션에 연결
        ↓
원천세 신고 화면 캡처
        ↓
AI Vision/OCR 또는 사전 정의 좌표맵으로 필드 위치 파악
        ↓
canvas 좌표에 실제 마우스 클릭 이벤트 전송
        ↓
키보드 입력 또는 클립보드 붙여넣기로 값 입력
        ↓
화면 캡처 및 네트워크 요청으로 입력값 검증
        ↓
임시저장 또는 검증 요청 확인
        ↓
최종 제출은 사람 승인 후 진행
```

즉, AI가 직접 canvas 내부 객체를 조작하는 것이 아니라, **AI는 필드 위치 인식과 검증에 사용하고, 실제 입력은 Playwright/CDP/RPA를 통해 사용자 행동처럼 수행**하는 구조가 적합하다.

---

## 2. 왜 canvas 화면은 일반 DOM 자동화가 어려운가

일반 웹 입력 화면은 다음과 같은 HTML 구조를 갖는다.

```html
<input name="paymentAmount" value="" />
<select name="incomeType">...</select>
<textarea name="memo"></textarea>
```

이 경우 자동화 코드는 다음처럼 작성할 수 있다.

```ts
await page.fill('input[name="paymentAmount"]', '12500000');
await page.selectOption('select[name="incomeType"]', '근로소득');
```

하지만 `canvas`는 화면에 픽셀을 그리는 요소다.

```html
<canvas width="1200" height="800"></canvas>
```

canvas 안에 보이는 표, 입력칸, 글자, 커서, 셀 테두리는 대부분 브라우저 DOM에 개별 요소로 존재하지 않는다. 즉, 화면에 `총지급액`이라는 글자가 보이더라도 DOM 상에는 다음과 같은 요소가 없을 수 있다.

```html
<input name="totalPaymentAmount" />
```

따라서 다음과 같은 방식은 실패할 가능성이 높다.

```ts
await page.fill('input[name="totalPaymentAmount"]', '12500000');
await page.locator('text=총지급액').click();
```

canvas 기반 화면에서는 자동화를 다음처럼 봐야 한다.

- DOM 자동화가 아니라 **화면 자동화**다.
- 필드 선택은 selector가 아니라 **좌표**로 한다.
- 텍스트 인식은 DOM text가 아니라 **OCR/AI Vision**으로 한다.
- 값 입력은 `element.value`가 아니라 **키보드 이벤트**로 한다.

---

## 3. 전체 접근 방식의 우선순위

권장 우선순위는 다음과 같다.

| 우선순위 | 방법 | 설명 | 권장도 |
|---:|---|---|---|
| 1 | 숨겨진 input/textarea 확인 | canvas처럼 보이지만 실제 입력은 hidden input이 담당할 수 있음 | 매우 높음 |
| 2 | Playwright/CDP 좌표 기반 입력 | canvas 위치를 계산해 클릭 후 키보드 입력 | 높음 |
| 3 | AI Vision/OCR 좌표 인식 | 라벨과 입력칸 위치를 이미지에서 탐지 | 높음 |
| 4 | HTTP proxy 분석 | 실제 저장 요청과 응답을 분석해 검증에 활용 | 높음 |
| 5 | 내부 API 직접 호출 | 임시저장/조회/검증에 한해 제한 검토 | 낮음~중간 |
| 6 | 최종 제출 자동화 | 신고·제출 책임 리스크가 큼 | 낮음 |

---

## 4. 1단계: 숨겨진 입력 요소 확인

canvas 기반 UI라도 실제 텍스트 입력을 위해 숨겨진 `input`, `textarea`, `contenteditable` 요소를 사용할 수 있다.

따라서 먼저 DevTools Console에서 다음을 확인한다.

### 4.1 현재 포커스 요소 확인

원천세 신고 화면에서 입력칸처럼 보이는 영역을 사람이 클릭한 뒤 콘솔에서 실행한다.

```js
document.activeElement
```

결과가 다음 중 하나라면 직접 입력 가능성이 있다.

```html
<input ...>
<textarea ...></textarea>
<div contenteditable="true">...</div>
```

반대로 결과가 계속 `body`, `canvas`, 또는 특정 wrapper div라면 DOM 입력이 아니라 canvas 내부 상태로 처리될 가능성이 높다.

### 4.2 입력 가능 요소 전체 탐색

```js
[...document.querySelectorAll('input, textarea, [contenteditable="true"]')]
  .map((el, i) => ({
    i,
    tag: el.tagName,
    type: el.type,
    value: el.value,
    rect: el.getBoundingClientRect(),
    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
  }))
```

확인할 포인트는 다음과 같다.

- 보이지 않는 hidden textarea가 있는가?
- 클릭할 때 activeElement가 바뀌는가?
- 값을 입력하면 hidden input의 value가 바뀌는가?
- iframe 내부에 입력 요소가 있는가?

### 4.3 iframe 내부 확인

업무용 SaaS는 iframe 안에 화면을 넣는 경우가 많다.

```js
[...document.querySelectorAll('iframe')].map((f, i) => ({
  i,
  src: f.src,
  rect: f.getBoundingClientRect()
}))
```

Playwright에서는 모든 frame을 순회하면서 canvas나 input을 찾는 방식이 필요하다.

```ts
for (const frame of page.frames()) {
  const canvasCount = await frame.locator('canvas').count().catch(() => 0);
  const inputCount = await frame.locator('input, textarea').count().catch(() => 0);

  console.log(frame.url(), { canvasCount, inputCount });
}
```

---

## 5. 2단계: Playwright/CDP로 로그인된 브라우저에 연결

로그인은 사람이 미리 해둔다고 했으므로, 자동화 프로그램이 로그인 자체를 처리할 필요는 없다.

권장 방식은 다음과 같다.

1. Chrome을 remote debugging 모드로 실행한다.
2. 사용자가 해당 브라우저에서 WEHAGO에 로그인한다.
3. 원천세 신고 화면까지 이동한다.
4. Playwright가 이미 로그인된 브라우저 세션에 연결한다.
5. 자동화는 해당 페이지를 조작한다.

### 5.1 Chrome 실행 예시 - Linux/macOS

```bash
google-chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/wehago-automation-profile
```

### 5.2 Chrome 실행 예시 - Windows

```bat
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="C:\wehago-automation-profile"
```

### 5.3 Playwright에서 기존 브라우저에 연결

```ts
import { chromium } from 'playwright';

const browser = await chromium.connectOverCDP('http://localhost:9222');
const context = browser.contexts()[0];

const page = context.pages().find(p => p.url().includes('wehago'));
if (!page) {
  throw new Error('WEHAGO 페이지를 찾지 못했습니다.');
}

await page.bringToFront();
```

---

## 6. 3단계: canvas 위치 찾기

canvas 입력 자동화의 핵심은 화면 좌표 계산이다.

Playwright의 `mouse.click(x, y)`는 브라우저 viewport 기준 좌표를 사용한다. 따라서 canvas 내부 좌표를 클릭하려면 다음 계산이 필요하다.

```text
실제 클릭 x = canvas의 viewport x 위치 + canvas 내부 x
실제 클릭 y = canvas의 viewport y 위치 + canvas 내부 y
```

### 6.1 기본 좌표 클릭 예시

```ts
const canvas = page.locator('canvas').first();
const box = await canvas.boundingBox();

if (!box) {
  throw new Error('canvas 위치를 찾지 못했습니다.');
}

const canvasX = 420;
const canvasY = 215;

await page.mouse.click(box.x + canvasX, box.y + canvasY);
await page.keyboard.press('ControlOrMeta+A');
await page.keyboard.type('202605');
await page.keyboard.press('Tab');
```

### 6.2 iframe 안 canvas 처리

```ts
let targetFrame = page.mainFrame();

for (const frame of page.frames()) {
  const count = await frame.locator('canvas').count().catch(() => 0);
  if (count > 0) {
    targetFrame = frame;
    break;
  }
}

const canvas = targetFrame.locator('canvas').first();
const box = await canvas.boundingBox();

if (!box) {
  throw new Error('canvas 위치를 찾지 못했습니다.');
}
```

### 6.3 canvas bitmap 좌표와 CSS 좌표 차이

canvas는 HTML 속성상 bitmap 크기와 CSS 표시 크기가 다를 수 있다.

예를 들어:

```html
<canvas width="2400" height="1600" style="width: 1200px; height: 800px"></canvas>
```

이 경우 bitmap 좌표와 화면 좌표가 2배 차이 난다.

확인 코드:

```ts
const info = await canvas.evaluate((el: HTMLCanvasElement) => ({
  cssWidth: el.getBoundingClientRect().width,
  cssHeight: el.getBoundingClientRect().height,
  bitmapWidth: el.width,
  bitmapHeight: el.height
}));

console.log(info);
```

변환 함수:

```ts
function canvasBitmapToViewport(
  box: { x: number; y: number; width: number; height: number },
  bitmapX: number,
  bitmapY: number,
  bitmapWidth: number,
  bitmapHeight: number
) {
  return {
    x: box.x + (bitmapX / bitmapWidth) * box.width,
    y: box.y + (bitmapY / bitmapHeight) * box.height
  };
}
```

---

## 7. 4단계: canvas 필드 입력 구현

원천세 신고 화면의 필드 좌표를 알고 있다면 다음처럼 입력 함수를 만들 수 있다.

```ts
const fields = {
  귀속연월: { x: 430, y: 210 },
  지급연월: { x: 560, y: 210 },
  총지급액: { x: 720, y: 410 },
  소득세: { x: 880, y: 410 },
  지방소득세: { x: 1010, y: 410 }
};

async function fillCanvasField(name: keyof typeof fields, value: string) {
  const pos = fields[name];

  await page.mouse.click(box.x + pos.x, box.y + pos.y);

  // 기존 값 전체 선택 후 삭제
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.press('Backspace');

  // 숫자·날짜·금액 필드는 type이 비교적 안정적
  await page.keyboard.type(value, { delay: 20 });

  // 포커스 이동으로 값 확정
  await page.keyboard.press('Tab');
}

await fillCanvasField('귀속연월', '202605');
await fillCanvasField('지급연월', '202606');
await fillCanvasField('총지급액', '12500000');
await fillCanvasField('소득세', '375000');
await fillCanvasField('지방소득세', '37500');
```

### 7.1 한글 입력 처리

숫자, 날짜, 금액은 `keyboard.type()`으로 충분한 경우가 많다.

하지만 한글 입력이 필요한 필드는 IME 문제 때문에 직접 타이핑보다 클립보드 붙여넣기가 안정적인 경우가 있다.

```ts
async function pasteText(value: string) {
  await page.evaluate(async (text) => {
    await navigator.clipboard.writeText(text);
  }, value);

  await page.keyboard.press('ControlOrMeta+V');
}
```

단, 브라우저 권한 설정이나 보안 정책에 따라 clipboard API가 제한될 수 있다.

대안은 OS 레벨 RPA 도구, 예를 들어 Python `pyautogui`, AutoHotkey, Power Automate Desktop 등을 사용하는 것이다.

---

## 8. 5단계: AI Vision/OCR로 필드 좌표 찾기

화면 좌표가 완전히 고정되어 있으면 사전 정의 좌표맵만으로도 가능하다.

하지만 다음 요소 때문에 절대좌표만 사용하는 방식은 취약하다.

- 브라우저 확대/축소 비율 변경
- 모니터 해상도 변경
- WEHAGO 사이드바 열림/닫힘
- 상단 메뉴 높이 변경
- 팝업/알림 배너 표시
- 화면 스크롤 위치 변경
- WEHAGO UI 업데이트

따라서 안정성을 높이려면 **라벨 앵커 기반 좌표 계산**을 사용하는 것이 좋다.

### 8.1 절대 좌표 방식

```json
{
  "귀속연월": { "x": 430, "y": 210 },
  "지급연월": { "x": 560, "y": 210 },
  "총지급액": { "x": 720, "y": 410 }
}
```

장점:

- 구현이 쉽다.
- 화면이 고정되어 있으면 빠르고 안정적이다.

단점:

- 화면 레이아웃이 조금만 바뀌어도 실패한다.
- 해상도/확대비/스크롤에 약하다.

### 8.2 앵커 기반 좌표 방식

```ts
type AnchorField = {
  label: string;
  dx: number;
  dy: number;
};

const fieldMap: Record<string, AnchorField> = {
  귀속연월: { label: '귀속연월', dx: 90, dy: 0 },
  지급연월: { label: '지급연월', dx: 90, dy: 0 },
  총지급액: { label: '총지급액', dx: 70, dy: 22 },
  소득세: { label: '소득세', dx: 65, dy: 22 },
  지방소득세: { label: '지방소득세', dx: 80, dy: 22 }
};
```

AI/OCR이 `총지급액` 라벨의 위치를 찾으면:

```ts
const inputX = labelX + fieldMap.총지급액.dx;
const inputY = labelY + fieldMap.총지급액.dy;
```

이 방식의 장점은 화면이 조금 움직여도 라벨을 다시 찾으면 입력칸 위치를 다시 계산할 수 있다는 점이다.

### 8.3 AI Vision 프롬프트 예시

```text
이 이미지는 WEHAGO 원천세 신고 입력 화면이다.
다음 라벨에 대응하는 입력칸의 중심 좌표를 viewport pixel 기준으로 찾아라.

찾을 필드:
- 귀속연월
- 지급연월
- 소득구분
- 인원
- 총지급액
- 소득세
- 지방소득세

반환 형식은 JSON만 허용한다.
각 필드는 {x, y, confidence, evidenceText} 형태로 반환한다.
confidence가 0.85 미만이면 null로 반환한다.
```

반환 예:

```json
{
  "귀속연월": {
    "x": 431,
    "y": 212,
    "confidence": 0.94,
    "evidenceText": "귀속연월 오른쪽 입력칸"
  },
  "지급연월": {
    "x": 561,
    "y": 212,
    "confidence": 0.92,
    "evidenceText": "지급연월 오른쪽 입력칸"
  },
  "총지급액": {
    "x": 721,
    "y": 408,
    "confidence": 0.91,
    "evidenceText": "총지급액 열의 첫 번째 행"
  }
}
```

### 8.4 confidence 기준

운영 환경에서는 다음 기준을 권장한다.

| confidence | 처리 방식 |
|---:|---|
| 0.95 이상 | 자동 입력 가능 |
| 0.85 ~ 0.95 | 입력 가능하나 사후 검증 필수 |
| 0.70 ~ 0.85 | 사람 검토 권장 |
| 0.70 미만 | 자동 입력 중단 |

---

## 9. 6단계: 입력 후 검증

세무 신고 업무에서는 입력 자체보다 검증이 더 중요하다.

검증은 최소 3단계로 나누는 것이 좋다.

```text
1. 화면 검증
2. 네트워크 요청 검증
3. 서버 응답 검증
```

### 9.1 화면 검증

입력 후 스크린샷을 찍고 AI/OCR로 값이 들어갔는지 확인한다.

```ts
await page.screenshot({
  path: 'after-input.png',
  fullPage: false
});
```

검증 프롬프트 예:

```text
이 이미지는 원천세 신고 입력 완료 화면이다.
다음 값이 화면에 정확히 입력되어 있는지 확인하라.

검증 대상:
- 귀속연월: 202605
- 지급연월: 202606
- 총지급액: 12,500,000
- 소득세: 375,000
- 지방소득세: 37,500

반환 형식은 JSON만 허용한다.
각 항목은 {expected, observed, match, confidence} 형태로 반환한다.
```

### 9.2 네트워크 요청 검증

입력 또는 임시저장 시 서버로 전송되는 payload를 확인한다.

검증 예:

```json
{
  "belongYm": "202605",
  "payYm": "202606",
  "paymentAmount": 12500000,
  "incomeTax": 375000,
  "localIncomeTax": 37500
}
```

자동화가 입력한 원본 데이터와 실제 서버 요청 payload가 일치하는지 비교한다.

### 9.3 서버 응답 검증

서버 응답에서 다음을 확인한다.

- 저장 성공 여부
- validation 오류 여부
- 경고 메시지
- 신고서 ID 또는 임시저장 ID
- 세액 불일치 여부
- 필수값 누락 여부

---

## 10. HTTP proxy 분석 접근

HTTP proxy 분석은 이 프로젝트에서 매우 유용하다.

다만 목적을 정확히 잡아야 한다.

권장 목적:

```text
canvas 자동화가 실제로 어떤 요청을 만들었는지 확인하고,
입력값과 서버 저장값의 불일치를 검출하는 검증 레이어 구축
```

비권장 목적:

```text
비공식 내부 API를 찾아서 인증·검증 흐름을 우회하거나,
최종 신고 제출 요청을 직접 replay하는 것
```

---

## 11. HTTP proxy 분석이 유용한 이유

canvas 화면은 DOM으로는 접근하기 어렵지만, 최종적으로 입력값은 서버로 전송된다.

HTTP proxy를 통해 다음을 확인할 수 있다.

| 확인 대상 | 의미 |
|---|---|
| endpoint | 저장, 조회, 검증, 제출 요청 URL |
| payload 구조 | 귀속연월, 지급연월, 총지급액 등의 key |
| 서버 validation | 필수값, 형식 오류, 세액 오류 응답 |
| CSRF/token | 요청 재현 가능성 판단 |
| session 처리 | 브라우저 세션 내 호출 필요 여부 |
| 임시저장/제출 구분 | 안전한 자동화 범위 결정 |
| WebSocket 사용 여부 | 일반 XHR/fetch가 아닐 가능성 확인 |

---

## 12. HTTP proxy 분석 도구 비교

| 도구 | 적합한 용도 | 특징 |
|---|---|---|
| Chrome DevTools Network | 1차 분석 | 가장 간단하고 덜 침습적 |
| Burp Suite | 사람이 보며 정밀 분석 | 요청/응답 history, intercept, repeater 등 강력 |
| mitmproxy | 자동 로그 수집/스크립팅 | Python 스크립트로 필터링·마스킹 가능 |
| OWASP ZAP | 무료 보안 테스트/대안 | 프록시 브라우저 및 보안 분석 기능 제공 |

추천 순서:

```text
Chrome DevTools Network
        ↓
Burp Suite 또는 mitmproxy 기록 모드
        ↓
필요 시 제한적인 요청 재현 테스트
        ↓
운영 반영 여부 검토
```

---

## 13. Chrome DevTools Network 분석 절차

처음에는 Chrome DevTools만으로도 많은 것을 확인할 수 있다.

절차:

1. 사람이 WEHAGO에 로그인한다.
2. 원천세 신고 화면으로 이동한다.
3. Chrome DevTools를 연다.
4. Network 탭을 선택한다.
5. `Fetch/XHR` 필터를 켠다.
6. 필요하면 `Preserve log`를 켠다.
7. 원천세 화면에서 값 하나를 입력한다.
8. 임시저장, 검증, 조회, 계산 버튼을 각각 실행한다.
9. 발생한 요청의 Request Payload, Response, Headers를 확인한다.

확인할 주요 항목:

- URL
- Method: GET/POST/PUT/PATCH
- Request Headers
- Cookies
- CSRF 관련 header
- Request Payload 또는 Form Data
- Response body
- Status code
- 요청 발생 시점

---

## 14. Burp/mitmproxy 사용 시 권장 원칙

업무용 세무 데이터가 오가는 화면이므로 처음부터 요청을 수정하거나 차단하지 않는다.

권장 원칙:

```text
Intercept off
History/logging only
민감정보 마스킹
테스트 사업자 또는 샘플 데이터 사용
최종 제출 요청 재현 금지
```

### 14.1 Burp 사용 흐름

1. Burp Suite 실행
2. Proxy 설정
3. 브라우저 proxy를 Burp로 지정
4. HTTPS 인증서 설치
5. Intercept는 끄고 HTTP history만 관찰
6. 원천세 화면에서 동작 수행
7. endpoint와 payload를 분류

### 14.2 mitmproxy 사용 흐름

1. mitmproxy 실행
2. 브라우저 proxy를 mitmproxy로 지정
3. 인증서 설치
4. 로그 스크립트로 WEHAGO 관련 요청만 저장
5. 민감정보 마스킹
6. 요청·응답 패턴 분석

---

## 15. mitmproxy 로그 수집 예시

다음 코드는 요청을 변조하지 않고, WEHAGO 관련 요청만 JSONL로 기록한다.

민감할 수 있는 key는 마스킹한다.

```python
# save_wehago_flows.py
from mitmproxy import http
import json
import re
from datetime import datetime

SENSITIVE_KEYS = re.compile(
    r"(password|passwd|token|authorization|cookie|resident|jumin|rrn|ssn)",
    re.I
)

def redact(obj):
    if isinstance(obj, dict):
        return {
            k: "***REDACTED***" if SENSITIVE_KEYS.search(k) else redact(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj

def request(flow: http.HTTPFlow):
    host = flow.request.pretty_host

    if "wehago" not in host.lower():
        return

    content_type = flow.request.headers.get("content-type", "")
    body = None

    if "application/json" in content_type:
        try:
            body = redact(json.loads(flow.request.get_text()))
        except Exception:
            body = "[unparseable json]"
    elif flow.request.method in ("POST", "PUT", "PATCH"):
        body = "[non-json body omitted]"

    record = {
        "time": datetime.now().isoformat(),
        "method": flow.request.method,
        "url": flow.request.pretty_url,
        "content_type": content_type,
        "body": body
    }

    with open("wehago_requests.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

실행:

```bash
mitmproxy -s save_wehago_flows.py
```

운영 환경에서는 request뿐 아니라 response도 기록할 수 있다.

```python
def response(flow: http.HTTPFlow):
    host = flow.request.pretty_host

    if "wehago" not in host.lower():
        return

    content_type = flow.response.headers.get("content-type", "")

    if "application/json" not in content_type:
        return

    try:
        body = redact(json.loads(flow.response.get_text()))
    except Exception:
        body = "[unparseable json]"

    record = {
        "time": datetime.now().isoformat(),
        "url": flow.request.pretty_url,
        "status_code": flow.response.status_code,
        "response": body
    }

    with open("wehago_responses.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
```

주의:

- 쿠키, Authorization, CSRF token, 주민번호, 급여 데이터는 평문 저장하지 않는다.
- 로그 파일은 암호화 저장하거나 별도 보안 폴더에 둔다.
- 실제 제출 요청은 재현하지 않는다.

---

## 16. HTTP proxy로 찾아야 할 요청 유형

원천세 신고 화면에서는 다음 요청들을 분류하는 것이 좋다.

| 요청 유형 | 예시 키워드 | 분석 목적 |
|---|---|---|
| 화면 초기 조회 | `load`, `search`, `list`, `detail` | 신고서 조회 구조 확인 |
| 코드 조회 | `code`, `common`, `incomeType` | 소득구분, 세목 코드 확인 |
| 계산 요청 | `calculate`, `calc`, `tax` | 세액 계산이 서버/클라이언트 중 어디서 되는지 확인 |
| 임시저장 | `save`, `temp`, `draft` | 안전한 저장 범위 확인 |
| 검증 | `validate`, `check` | 서버 validation rule 확인 |
| 신고서 생성 | `report`, `form`, `generate` | 전자신고 파일/서식 생성 여부 확인 |
| 최종 제출 | `submit`, `send`, `nts`, `hometax`, `reporting` | 자동화 제외 또는 사람 승인 필수 |

---

## 17. HTTP payload 구조 예시

실제 구조는 WEHAGO 내부 구현에 따라 다르지만, proxy 분석을 하면 대략 다음과 같은 구조를 발견할 수 있다.

### 17.1 단순 object 형태

```json
{
  "belongYm": "202605",
  "payYm": "202606",
  "incomeType": "근로소득",
  "personCount": 3,
  "paymentAmount": 12500000,
  "incomeTax": 375000,
  "localIncomeTax": 37500
}
```

### 17.2 grid row 형태

```json
{
  "rows": [
    {
      "rowId": "R1",
      "incomeCd": "A01",
      "payAmt": "12500000",
      "taxAmt": "375000",
      "localTaxAmt": "37500",
      "dirty": true
    }
  ]
}
```

### 17.3 diff/patch 형태

```json
{
  "changed": [
    {
      "path": "rows[0].payAmt",
      "oldValue": "",
      "newValue": "12500000"
    },
    {
      "path": "rows[0].taxAmt",
      "oldValue": "",
      "newValue": "375000"
    }
  ]
}
```

### 17.4 암호화/압축/난독화 형태

일부 서비스는 payload를 다음처럼 처리할 수 있다.

```json
{
  "data": "eyJyb3dzIjpbXX0=",
  "signature": "...",
  "timestamp": 1710000000000
}
```

이 경우 무리하게 우회하려 하기보다 브라우저 기반 자동화와 네트워크 검증에 집중하는 것이 좋다.

---

## 18. HTTP proxy 분석을 자동화 검증에 활용하는 방법

HTTP proxy 분석 결과를 운영에 반영하는 좋은 방법은 다음과 같다.

```text
자동화 입력 원본 데이터
        ↓
Playwright가 canvas에 입력
        ↓
사용자가 임시저장 또는 자동화가 임시저장 클릭
        ↓
proxy/CDP Network event로 저장 요청 payload 수집
        ↓
원본 데이터와 payload 비교
        ↓
서버 응답 validation 확인
        ↓
일치하면 다음 단계 진행
        ↓
불일치하면 즉시 중단 및 사람 검토
```

### 18.1 payload 비교 예시

```ts
type ExpectedData = {
  belongYm: string;
  payYm: string;
  paymentAmount: number;
  incomeTax: number;
  localIncomeTax: number;
};

function validatePayload(expected: ExpectedData, actual: any) {
  const errors: string[] = [];

  if (actual.belongYm !== expected.belongYm) {
    errors.push(`귀속연월 불일치: expected=${expected.belongYm}, actual=${actual.belongYm}`);
  }

  if (Number(actual.paymentAmount) !== expected.paymentAmount) {
    errors.push(`총지급액 불일치: expected=${expected.paymentAmount}, actual=${actual.paymentAmount}`);
  }

  if (Number(actual.incomeTax) !== expected.incomeTax) {
    errors.push(`소득세 불일치: expected=${expected.incomeTax}, actual=${actual.incomeTax}`);
  }

  return {
    ok: errors.length === 0,
    errors
  };
}
```

---

## 19. Playwright Network event로 proxy 없이 감시하기

외부 proxy를 쓰지 않고 Playwright 내부에서 네트워크 요청을 감시할 수도 있다.

```ts
page.on('request', async request => {
  const url = request.url();

  if (!url.includes('wehago')) return;
  if (!['POST', 'PUT', 'PATCH'].includes(request.method())) return;

  const postData = request.postData();

  console.log('REQUEST', {
    method: request.method(),
    url,
    postData
  });
});

page.on('response', async response => {
  const url = response.url();

  if (!url.includes('wehago')) return;

  const contentType = response.headers()['content-type'] || '';
  if (!contentType.includes('application/json')) return;

  try {
    const json = await response.json();
    console.log('RESPONSE', {
      url,
      status: response.status(),
      json
    });
  } catch {
    // JSON이 아니거나 파싱 실패
  }
});
```

이 방식의 장점:

- 별도 proxy 인증서 설치가 필요 없다.
- 로그인된 브라우저 자동화 코드와 한 프로세스에서 처리 가능하다.
- 운영 자동화에 통합하기 쉽다.

단점:

- TLS 레벨 proxy만큼 모든 상황을 잡지는 못할 수 있다.
- 브라우저 외부 요청은 보이지 않는다.
- WebSocket/Service Worker 관련 처리가 추가로 필요할 수 있다.

---

## 20. 내부 API 직접 호출에 대한 판단

HTTP proxy 분석을 하다 보면 내부 API를 직접 호출하고 싶어질 수 있다.

기술적으로는 다음과 같은 호출이 가능할 수 있다.

```ts
await page.evaluate(async (payload) => {
  const res = await fetch('/some/internal/save/api', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload),
    credentials: 'include'
  });

  return await res.json();
}, payload);
```

이 방식은 브라우저 내부에서 호출하므로 쿠키와 세션이 자동으로 포함될 수 있다.

하지만 운영 자동화의 기본 전략으로 삼기는 위험하다.

### 20.1 내부 API 직접 호출의 장점

- 좌표 자동화보다 빠르다.
- 화면 레이아웃 변화에 덜 민감하다.
- payload 검증이 명확하다.
- 대량 데이터 입력에 적합할 수 있다.

### 20.2 내부 API 직접 호출의 단점

- 공식 API가 아니므로 언제든 바뀔 수 있다.
- CSRF, 서명, timestamp, nonce 등 보안 로직이 있을 수 있다.
- 프론트엔드에서 수행하는 사전 검증을 건너뛸 수 있다.
- 약관 또는 내부 보안 정책과 충돌할 수 있다.
- 세무 신고 데이터의 책임 소재가 불명확해질 수 있다.
- 최종 제출 요청을 잘못 호출하면 큰 사고로 이어질 수 있다.

### 20.3 내부 API 직접 호출을 검토할 수 있는 범위

상대적으로 검토 가능한 범위:

- 코드 조회
- 신고서 조회
- 임시저장
- 서버 validation
- 세액 계산 미리보기

권장하지 않는 범위:

- 최종 제출
- 홈택스/전자신고 전송
- 인증/권한 우회
- token/nonce 우회
- 다른 사업자 데이터 접근

---

## 21. 권장 아키텍처

가장 권장하는 구조는 다음과 같다.

```text
[사용자]
  └─ WEHAGO 로그인 및 원천세 신고 화면 진입

[Automation Controller]
  ├─ Playwright/CDP로 로그인된 브라우저 연결
  ├─ canvas 위치 및 frame 탐색
  ├─ AI Vision/OCR로 필드 좌표 인식
  ├─ 좌표 클릭 + 키보드 입력
  ├─ 스크린샷 저장
  ├─ Network event 또는 proxy 로그 수집
  ├─ 입력 원본 데이터와 request payload 비교
  ├─ 서버 response validation 확인
  └─ 이상 시 중단 및 사람 검토 요청

[Human Approval]
  └─ 최종 신고·제출 전 승인
```

### 21.1 단계별 처리 흐름

```text
1. 자동화 시작
2. 로그인된 WEHAGO 탭 탐색
3. 원천세 신고 canvas 화면 확인
4. 화면 스크린샷 촬영
5. AI/OCR로 필드 위치 탐지
6. confidence 기준 확인
7. 각 필드 클릭 및 값 입력
8. 입력 후 스크린샷 촬영
9. 화면 OCR로 1차 검증
10. 임시저장 클릭
11. 저장 request payload 캡처
12. 원본 데이터와 payload 비교
13. response validation 확인
14. 불일치 시 중단
15. 일치 시 사람에게 최종 확인 요청
16. 사람 승인 후 제출
```

---

## 22. 운영 안정성 설계

### 22.1 실패 시 즉시 중단해야 하는 조건

- canvas를 찾지 못함
- 원천세 신고 화면이 아닌 것으로 판단됨
- AI field confidence가 기준 미만
- 입력 후 OCR 검증 실패
- request payload와 원본 데이터 불일치
- 서버 response에 validation error 존재
- 사업자번호/귀속연월/신고구분이 기대값과 다름
- 중복 신고 가능성이 감지됨
- 최종 제출 버튼이 예상 위치에 없음

### 22.2 재시도 정책

자동화는 무한 재시도하면 안 된다.

권장 재시도 정책:

| 단계 | 재시도 횟수 | 실패 시 |
|---|---:|---|
| 화면 로딩 | 2회 | 사람 검토 |
| canvas 탐색 | 1회 | 사람 검토 |
| 필드 좌표 인식 | 1회 | 사람 검토 |
| 개별 필드 입력 | 1회 | 해당 필드 중단 |
| 임시저장 | 1회 | 사람 검토 |
| 최종 제출 | 자동 재시도 금지 | 사람 판단 |

---

## 23. 감사 로그 설계

원천세 신고 자동화는 반드시 감사 로그를 남겨야 한다.

로그에 포함할 항목:

| 항목 | 설명 |
|---|---|
| 실행자 | 자동화를 실행한 사용자 |
| 실행 시각 | 시작/종료 시각 |
| 대상 사업자 | 사업자명 또는 내부 식별자 |
| 귀속연월 | 신고 대상 기간 |
| 입력 원본 데이터 hash | 민감정보 원문 대신 hash 저장 가능 |
| 입력 전 스크린샷 | 화면 상태 증빙 |
| 입력 후 스크린샷 | 입력 결과 증빙 |
| 저장 request 요약 | endpoint, 주요 payload hash |
| response 요약 | 성공/오류 코드 |
| 검증 결과 | 화면/OCR/payload 비교 결과 |
| 최종 승인자 | 제출 승인한 사람 |
| 제출 여부 | 제출/미제출/임시저장 |

### 23.1 민감정보 처리

다음 정보는 평문 로그 저장을 피한다.

- 주민등록번호
- 외국인등록번호
- 계좌번호
- 급여 상세액
- 인증 토큰
- 세션 쿠키
- Authorization header
- CSRF token
- 사업자 내부 식별자

필요하면 다음 방식으로 처리한다.

- masking: `900101-1******`
- hash: SHA-256 등
- encrypted storage: KMS 또는 OS 보안 저장소
- 접근권한 제한
- 로그 보존기간 설정

---

## 24. 보안 및 컴플라이언스 주의사항

이 자동화는 회계·세무·개인정보를 다룰 가능성이 높다.

따라서 다음 원칙을 권장한다.

### 24.1 인증 우회 금지

사람이 정상 로그인한 세션에 붙는 것은 비교적 안전한 방향이다.

하지만 다음은 피해야 한다.

- 로그인 자동화 중 CAPTCHA 우회
- OTP/2FA 우회
- 세션 쿠키 탈취 후 별도 서버에서 사용
- 권한 없는 사업자 데이터 접근
- CSRF/token 우회

### 24.2 최종 제출 자동화 제한

최종 제출은 다음 이유로 사람 승인 절차를 유지하는 것이 좋다.

- 잘못된 세액 신고 가능성
- 중복 제출 가능성
- 신고기한/가산세 관련 책임
- 고객사별 승인 프로세스
- 전자신고 파일 생성·전송 책임

### 24.3 테스트 데이터 사용

초기 분석과 개발은 실제 민감정보가 아닌 다음 환경에서 수행하는 것이 좋다.

- 테스트 사업자
- 샘플 급여 데이터
- 마스킹된 주민번호
- 제출 불가능한 임시저장 단계
- 내부 QA 계정

---

## 25. 구현 예시: 통합 자동화 골격

아래 코드는 전체 구조를 보여주기 위한 예시다.

실제 WEHAGO 화면 좌표, frame 구조, endpoint 등은 현장 분석 후 조정해야 한다.

```ts
import { chromium, Page, Frame } from 'playwright';

type FieldName = '귀속연월' | '지급연월' | '총지급액' | '소득세' | '지방소득세';

type FieldPosition = {
  x: number;
  y: number;
  confidence?: number;
};

type InputData = Record<FieldName, string>;

const inputData: InputData = {
  귀속연월: '202605',
  지급연월: '202606',
  총지급액: '12500000',
  소득세: '375000',
  지방소득세: '37500'
};

const fieldPositions: Record<FieldName, FieldPosition> = {
  귀속연월: { x: 430, y: 210 },
  지급연월: { x: 560, y: 210 },
  총지급액: { x: 720, y: 410 },
  소득세: { x: 880, y: 410 },
  지방소득세: { x: 1010, y: 410 }
};

async function findWehagoPage() {
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const context = browser.contexts()[0];

  const page = context.pages().find(p => p.url().includes('wehago'));
  if (!page) throw new Error('WEHAGO 페이지를 찾지 못했습니다.');

  await page.bringToFront();
  return page;
}

async function findCanvasFrame(page: Page): Promise<Frame> {
  for (const frame of page.frames()) {
    const count = await frame.locator('canvas').count().catch(() => 0);
    if (count > 0) return frame;
  }

  throw new Error('canvas가 포함된 frame을 찾지 못했습니다.');
}

async function fillCanvasField(
  page: Page,
  canvasBox: { x: number; y: number },
  pos: FieldPosition,
  value: string
) {
  if (pos.confidence !== undefined && pos.confidence < 0.85) {
    throw new Error(`필드 좌표 confidence가 낮습니다: ${pos.confidence}`);
  }

  await page.mouse.click(canvasBox.x + pos.x, canvasBox.y + pos.y);
  await page.keyboard.press('ControlOrMeta+A');
  await page.keyboard.press('Backspace');
  await page.keyboard.type(value, { delay: 20 });
  await page.keyboard.press('Tab');
}

async function main() {
  const page = await findWehagoPage();

  // 네트워크 감시
  page.on('request', request => {
    const url = request.url();
    if (!url.includes('wehago')) return;
    if (!['POST', 'PUT', 'PATCH'].includes(request.method())) return;

    console.log('[REQUEST]', request.method(), url, request.postData());
  });

  page.on('response', async response => {
    const url = response.url();
    if (!url.includes('wehago')) return;

    const contentType = response.headers()['content-type'] || '';
    if (!contentType.includes('application/json')) return;

    try {
      const json = await response.json();
      console.log('[RESPONSE]', response.status(), url, json);
    } catch {
      // ignore
    }
  });

  const frame = await findCanvasFrame(page);
  const canvas = frame.locator('canvas').first();
  const box = await canvas.boundingBox();

  if (!box) throw new Error('canvas boundingBox를 찾지 못했습니다.');

  await page.screenshot({ path: 'before-input.png', fullPage: false });

  for (const [name, value] of Object.entries(inputData) as [FieldName, string][]) {
    await fillCanvasField(page, box, fieldPositions[name], value);
  }

  await page.screenshot({ path: 'after-input.png', fullPage: false });

  console.log('입력 완료. 임시저장/검증 단계로 진행하기 전에 화면과 네트워크 로그를 확인하세요.');
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
```

---

## 26. 추천 개발 단계

### Phase 1: 관찰 및 좌표 검증

목표:

- WEHAGO 원천세 신고 화면이 실제로 canvas 기반인지 확인
- iframe 구조 확인
- 숨겨진 input 존재 여부 확인
- canvas 좌표 클릭으로 값 입력 가능 여부 확인

산출물:

- 화면 구조 분석 문서
- canvas 좌표맵 초안
- 입력 가능 필드 목록

### Phase 2: Playwright 입력 PoC

목표:

- 로그인된 브라우저에 CDP로 연결
- canvas 좌표 클릭
- 숫자/날짜/금액 입력
- 입력 후 스크린샷 저장

산출물:

- Playwright PoC 코드
- before/after 스크린샷
- 실패 케이스 목록

### Phase 3: AI/OCR 좌표 인식

목표:

- 라벨 기반 필드 위치 탐지
- confidence 기준 수립
- 좌표맵 자동 보정

산출물:

- AI Vision 프롬프트
- 필드별 confidence 기준
- 앵커 기반 좌표맵

### Phase 4: HTTP proxy/Network 분석

목표:

- 저장/조회/검증 요청 식별
- request payload 구조 분석
- response validation 구조 분석

산출물:

- endpoint 목록
- payload key mapping
- validation error catalog

### Phase 5: 검증 레이어 구축

목표:

- 입력 원본 데이터와 화면 OCR 결과 비교
- 입력 원본 데이터와 request payload 비교
- 서버 response 검증

산출물:

- 검증 함수
- 중단 조건
- 감사 로그 포맷

### Phase 6: 제한 운영

목표:

- 특정 신고 유형/사업자/기간에 제한 적용
- 임시저장까지만 자동화
- 최종 제출은 사람 승인

산출물:

- 운영 매뉴얼
- 장애 대응 절차
- 승인 프로세스

---

## 27. 의사결정 요약

| 질문 | 권장 답변 |
|---|---|
| canvas 안 필드를 DOM selector로 접근할 수 있는가? | 일반적으로 불가능 |
| AI가 canvas 내부 필드에 직접 값을 넣을 수 있는가? | 직접은 불가, 좌표 인식과 검증에 활용 가능 |
| 가장 현실적인 입력 방식은? | Playwright/CDP 기반 좌표 클릭 + 키보드 입력 |
| 로그인 자동화가 필요한가? | 아니오, 사람이 로그인 후 자동화가 세션에 연결하는 방식 권장 |
| HTTP proxy 분석은 유용한가? | 매우 유용, 특히 검증 레이어 구축에 적합 |
| 내부 API 직접 호출을 해도 되는가? | 조회/임시저장/검증에 한해 신중히 검토, 제출은 비권장 |
| 최종 신고 제출도 자동화할 것인가? | 사람 승인 유지 권장 |
| 가장 중요한 안전장치는? | 화면 검증 + request payload 검증 + 서버 response 검증 + 감사 로그 |

---

## 28. 최종 권장안

WEHAGO 원천세 신고 canvas 화면 자동화는 다음 방식으로 진행하는 것이 가장 현실적이다.

```text
DOM 자동화가 아니라 화면 자동화로 접근한다.

공식 API가 없으므로 내부 API 직접 호출을 기본값으로 삼지 않는다.

로그인은 사람이 직접 수행하고,
자동화는 로그인된 브라우저 세션에 Playwright/CDP로 연결한다.

canvas 화면은 AI Vision/OCR 또는 사전 좌표맵으로 필드 위치를 찾고,
실제 입력은 마우스 클릭과 키보드 이벤트로 수행한다.

HTTP proxy 또는 Playwright Network event를 통해
입력 후 서버로 전송되는 payload와 response를 확인한다.

자동화 결과가 화면, payload, 서버 응답에서 모두 일치할 때만 다음 단계로 진행한다.

최종 신고·제출은 자동화하지 않거나,
최소한 사람 승인 절차를 반드시 둔다.
```

---

## 29. 참고 링크

- MDN Canvas API: https://developer.mozilla.org/docs/Web/API/Canvas_API/Tutorial/Basic_usage
- Playwright `connectOverCDP`: https://playwright.dev/docs/api/class-browsertype
- Playwright Mouse API: https://playwright.dev/docs/api/class-mouse
- Chrome DevTools Network Panel: https://developer.chrome.com/docs/devtools/network/overview
- Chrome DevTools Protocol Input domain: https://chromedevtools.github.io/devtools-protocol/tot/Input/
- Burp Suite Proxy: https://portswigger.net/burp/documentation/desktop/tools/proxy/getting-started
- Burp Suite HTTP history: https://portswigger.net/burp/documentation/desktop/tools/proxy/http-history
- mitmproxy 작동 방식: https://docs.mitmproxy.org/stable/concepts/how-mitmproxy-works/
- OWASP ZAP 시작 문서: https://www.zaproxy.org/docs/desktop/start/

---

## 30. 한 문장 요약

**WEHAGO 원천세 신고 자동화는 canvas 내부를 DOM처럼 조작하려 하기보다, 로그인된 브라우저에 붙어 AI Vision으로 좌표를 인식하고 Playwright/RPA로 입력하며, HTTP proxy 또는 Network event로 실제 저장 payload를 검증하는 RPA+Vision+Network Validation 구조가 가장 안전하고 현실적이다.**
