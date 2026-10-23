# 웹 앱(Next.js) 첫 화면 무게

웹 앱은 Vercel에 정적 페이지로 올라가고, 답은 브라우저가 API(Cloud Run)에서 직접 받는다(ADR-0008).
화면이 늦게 뜨는 원인은 두 가지뿐이다. 페이지마다 처음 받는 JS와 홈 사진이다.

## 2026-10-23: 마크다운은 답이 올 때, 사진은 보이는 크기로

**측정 (운영 홈, 앱 안 브라우저):** HTML 5KB, TTFB 53ms, JS 청크 172KB(전송량).
홈 사진 3장이 357KB였다. Unsplash 링크가 `w=1200`만 주고 있었다. 세로 사진 원본(1200x1924)이 약 440px 너비의 4:3 틀로 그대로 왔다.

**`next build`의 First Load JS:** 마크다운(`react-markdown` + `remark-gfm`)을 쓰는 페이지만 무거웠다.

| 페이지 | 전 | 후 |
| --- | ---: | ---: |
| `/chat` | 232 kB | **188 kB** |
| `/reports` | 222 kB | **178 kB** |
| `/visit-prep` | 230 kB | **184 kB** |
| 나머지 페이지 | 104~179 kB | 같음 |

- **마크다운:** `components/Markdown.tsx`가 `MarkdownBody`를 `React.lazy`로 따로 받는다. 마크다운은 답이 온 뒤에만 그린다. 묶음이 오기 전에는 같은 글을 줄바꿈만 살려 보여 준다.
- **홈 사진:** `components/HeroImage.tsx`가 Unsplash에서 4:3으로 잘라 480·800·1200px 중 화면에 맞는 것을 받는다(`srcset`, `sizes`). 첫 사진만 `fetchPriority=high`이다. 로컬 확인(창 1024px, 배율 1.25): 사진 4번 요청 138KB(전 357KB). 미리 받기가 480px을 한 번 더 받는다(20KB).
- 바꾸지 않은 것: Supabase 로그인 라이브러리(로그인 화면들의 약 65kB)는 첫 화면에서 로그인 상태를 알아야 해서 그대로 둔다. Next 이미지 최적화는 Vercel 사용량이 들고 Unsplash가 이미 크기를 맞춰 준다.
