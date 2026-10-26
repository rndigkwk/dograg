import type { Overview } from "@/lib/stats";

const REPO = "https://github.com/rndigkwk/dograg";
const DOC = (path: string) => `${REPO}/blob/main/${path}`;

const FEATURES: [title: string, text: string][] = [
  ["건강 상담", "수의사 상담 19,206건에서 비슷한 사례를 찾아 근거와 함께 답합니다. 응급 신호는 답보다 먼저 알리고, 근거가 없으면 지어내지 않고 보류합니다."],
  ["시설 찾기", "동물병원·약국·미용·위탁·장묘·동반 시설 38,529곳을 지역이나 현재 위치로 찾습니다."],
  ["지역별 진료비", "농림축산식품부 2025 조사의 시·군·구 통계로 진찰료·접종·검사비를 전국과 비교합니다. 실제 병원 가격은 아닙니다."],
  ["보고서 분석", "반려동물 보고서 5종(922쪽)에서 수치를 찾아 근거 쪽수와 함께 정리합니다."],
  ["방문 준비 보고서", "여러 에이전트가 증상·병원·비용을 나눠 조사하고, 검수자가 문장마다 근거와 대조한 보고서를 만듭니다."],
  ["관리 일정", "예방접종·구충·심장사상충 같은 관리 일정을 이 기기나 계정에 저장하고 다음 할 때를 알려 줍니다."],
];

// The README's key metrics (same evaluation set before and after; numbers in docs/improvement-log.md).
const METRICS: [what: string, before: string, after: string][] = [
  ["건강 검색: 쓸모 있는 근거가 상위 3건에 있는 질문 (100문항)", "0.46", "0.84"],
  ["보고서 답변: 기준 답과 맞음 (18문항 × 2회)", "23/36", "30/36"],
  ["근거 없는 질문을 보류함 (20문항)", "0/20", "16/20"],
  ["응급 신호 감지 (응급 20 / 비응급 20)", "1/20", "19/20, 오탐 0"],
  ["방문 준비 보고서 검수 통과율 (상담 12개)", "0.70", "1.00"],
  ["건강 답변 시간 p90 (40문항)", "18.5초", "11.4초"],
];

const STACK: [part: string, what: string][] = [
  ["화면", "Next.js 15 (Vercel)"],
  ["API", "FastAPI, LangGraph (Google Cloud Run, 서울)"],
  ["검색", "Supabase pgvector + PGroonga 하이브리드, 미세조정한 한국어 임베딩(ko-sroberta)"],
  ["모델", "OpenAI 모델로 답변·근거 평가·검수"],
  ["계정", "Supabase 로그인(Google)과 행 단위 보안(RLS)"],
  ["운영", "답을 바꾸는 PR은 실제 모델로 병합 전 평가, 매주 회귀 평가와 응답 시간 보고"],
];

function Tile({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-xl border border-line bg-white p-3">
      <p className="text-2xl font-bold tabular-nums">{value}</p>
      <p className="text-sm text-muted">{label}</p>
    </div>
  );
}

/** The 소개 page's first tab: what RagDog is, what it does, how it was measured and built. */
export function ProjectAbout() {
  return (
    <div className="space-y-5">
      <section className="space-y-2 rounded-xl border border-line bg-white p-4">
        <h2 className="text-lg font-bold">라그도그는 무엇인가요</h2>
        <p>
          반려견 보호자가 짧게 묻는 건강 질문에, 공개 상담 사례와 공공기관 자료를 근거로 답하는 서비스입니다. 틀린 건강 정보는 해롭기 때문에
          <strong> 근거가 없으면 지어내지 않고 보류하고, 응급 신호는 답보다 먼저 알립니다.</strong> 진단이나 응급 처치를 대신하지 않습니다.
        </p>
        <p className="text-sm text-muted">
          엔코아 AI 캠퍼스 4인 팀 프로젝트(2026-08)를 발표 뒤 오현탁이 혼자 이어서(2026-09~10, PR 300여 개) 측정하며 개선했습니다.
        </p>
      </section>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile value="19,206건" label="수의사 상담 사례" />
        <Tile value="38,529곳" label="반려동물 시설" />
        <Tile value="922쪽" label="보고서 5종" />
        <Tile value="201곳" label="진료비 통계가 있는 시·군·구" />
      </div>

      <section className="rounded-xl border border-line bg-white p-4">
        <h2 className="mb-2 text-lg font-bold">할 수 있는 일</h2>
        <ul className="grid gap-3 sm:grid-cols-2">
          {FEATURES.map(([title, text]) => (
            <li key={title}>
              <p className="font-semibold">{title}</p>
              <p className="text-sm">{text}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-xl border border-line bg-white p-4">
        <h2 className="mb-1 text-lg font-bold">어떻게 만들었나요</h2>
        <p className="mb-3 text-sm">
          질문을 유형별 경로로 나누고(LangGraph), 하이브리드 검색으로 근거를 찾고, 근거가 쓸 만한지 평가한 뒤에만 답합니다. 평가 세트를 먼저 만들고,
          고칠 때마다 같은 세트로 전후를 재서 효과가 없는 변경(리랭커, 큰 임베딩 모델 등)은 넣지 않았습니다.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <caption className="mb-1 text-left text-muted">같은 평가 세트로 잰 전후</caption>
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-3">지표</th>
                <th className="py-1 pr-3 text-right">이전</th>
                <th className="py-1 text-right">이후</th>
              </tr>
            </thead>
            <tbody>
              {METRICS.map(([what, before, after]) => (
                <tr key={what} className="border-t border-line">
                  <td className="py-1 pr-3">{what}</td>
                  <td className="py-1 pr-3 text-right tabular-nums text-muted">{before}</td>
                  <td className="py-1 text-right font-semibold tabular-nums">{after}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-line bg-white p-4">
        <h2 className="mb-2 text-lg font-bold">구성</h2>
        <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[6rem_1fr]">
          {STACK.map(([part, what]) => (
            <div key={part} className="contents">
              <dt className="font-semibold">{part}</dt>
              <dd className="mb-1 sm:mb-0">{what}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-sm">
          자세한 기록:{" "}
          <a href={REPO} target="_blank" rel="noreferrer" className="text-accent underline">GitHub 저장소</a> ·{" "}
          <a href={DOC("docs/improvement-log.md")} target="_blank" rel="noreferrer" className="text-accent underline">개선 기록</a> ·{" "}
          <a href={DOC("docs/adr/README.md")} target="_blank" rel="noreferrer" className="text-accent underline">설계 결정(ADR)</a>
        </p>
      </section>
    </div>
  );
}

type Source = { title: string; publisher: string; url: string; use: string; scale: string; terms?: string };

const SOURCES: { group: string; items: Source[] }[] = [
  {
    group: "건강 상담",
    items: [
      {
        title: "반려견 성장 및 질병관련 말뭉치 데이터",
        publisher: "AI Hub (과학기술정보통신부·한국지능정보사회진흥원)",
        url: "https://aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&aihubDataSe=data&dataSetSn=71879",
        use: "건강 상담의 검색·답변 근거, 검색 평가, 임베딩 미세조정",
        scale: "상담 19,206건",
        terms: "AI Hub 이용정책에 따라 원본은 공개하지 않고, 답변에는 짧은 인용만 보여 줍니다.",
      },
    ],
  },
  {
    group: "일상 관리 지침",
    items: [
      { title: "건강한 반려문화 조성을 위한 행동지도 윤리 가이드라인", publisher: "농림수산식품교육문화정보원 동물사랑배움터", url: "https://apms.epis.or.kr/home/kor/board.do?menuPos=16&act=detail&idx=1454", use: "일상 관리 질문의 근거", scale: "" },
      { title: "반려견 공공예절 교육 자료", publisher: "농림수산식품교육문화정보원 동물사랑배움터", url: "https://apms.epis.or.kr/home/kor/board.do?menuPos=16&act=detail&idx=257", use: "일상 관리 질문의 근거", scale: "" },
      { title: "반려동물 가족을 위한 재난 대응 가이드라인", publisher: "농림수산식품교육문화정보원 동물사랑배움터", url: "https://apms.epis.or.kr/home/kor/board.do?menuPos=16&act=detail&idx=639", use: "재난 대비 질문의 근거", scale: "" },
      { title: "반려동물과의 이별, 미리 알고 함께 준비합니다", publisher: "농림수산식품교육문화정보원 동물사랑배움터", url: "https://apms.epis.or.kr/home/kor/board.do?menuPos=16&act=detail&idx=1542", use: "사후 절차 질문의 근거", scale: "" },
      { title: "함께여서 더 특별한 반려동물과의 여름나기", publisher: "농림축산식품부 (공공누리 제1유형)", url: "https://www.mafra.go.kr/bbs/home/792/578176/artclView.do", use: "열사병 예방 질문의 근거", scale: "" },
    ],
  },
  {
    group: "보고서 5종",
    items: [
      { title: "2025 한국 반려동물 보고서", publisher: "KB경영연구소 (2025)", url: "https://kbthink.com/investment/deepdive/research/250629-2.html", use: "보고서 분석", scale: "112쪽" },
      { title: "반려동물 복지실태와 개선과제", publisher: "한국농촌경제연구원 (2024)", url: "https://repository.krei.re.kr/handle/2018.oak/31457", use: "보고서 분석", scale: "273쪽" },
      { title: "반려동물 산업 조사체계 진단 및 실태조사", publisher: "한국농촌경제연구원 (2024)", url: "https://repository.krei.re.kr/handle/2018.oak/31235", use: "보고서 분석", scale: "284쪽" },
      { title: "반려동물 의료·보험서비스 시장 진단 및 개선방안 연구", publisher: "한국소비자원", url: "https://www.kca.go.kr/home/sub.do?menukey=6101&mode=view&no=1004453818", use: "보고서 분석, 방문 준비 보고서의 비용 조사", scale: "184쪽" },
      { title: "반려동물 장묘서비스 이용 실태조사", publisher: "한국소비자원 (2022)", url: "https://www.kca.go.kr/smartconsumer/sub.do?menukey=7301&mode=view&no=1003450594", use: "보고서 분석", scale: "69쪽" },
    ],
  },
  {
    group: "진료비",
    items: [
      {
        title: "동물병원 진료비 현황 (2025 조사)",
        publisher: "농림축산식품부",
        url: "https://animalclinicfee.or.kr/info/payInfo.do",
        use: "지역별 진료비, 채팅의 진료비 답, 방문 준비 보고서의 진료비",
        scale: "6,413행 (시·군·구 201곳)",
        terms: "지역 조사 통계(중간값·평균)이며 개별 병원의 가격이 아닙니다.",
      },
    ],
  },
];

function SourceRow({ source }: { source: Source }) {
  return (
    <li className="border-t border-line py-2 first:border-t-0">
      <a href={source.url} target="_blank" rel="noreferrer" className="font-semibold text-accent underline">
        {source.title}
      </a>
      <p className="text-sm text-muted">
        {source.publisher}
        {source.scale ? ` · ${source.scale}` : ""}
      </p>
      <p className="text-sm">쓰는 곳: {source.use}</p>
      {source.terms ? <p className="text-xs text-muted">{source.terms}</p> : null}
    </li>
  );
}

/** The 소개 page's last tab: every source the answers and lists come from, with links. */
export function DataSources({ places }: { places: Overview["place_sources"] }) {
  return (
    <div className="space-y-4">
      <p className="text-sm">
        라그도그의 답과 목록은 아래 자료에서만 나옵니다. 공공데이터가 아닌 자료(상담 말뭉치, 보고서 PDF, 교육자료)는 저작권과 이용 조건 때문에 원본을 공개하지 않고,
        답변에 짧게 인용하며 기관·자료명·쪽을 함께 밝힙니다.
      </p>
      {SOURCES.map(({ group, items }) => (
        <section key={group} className="rounded-xl border border-line bg-white p-4">
          <h2 className="mb-1 font-bold">{group}</h2>
          <ul>
            {items.map((source) => <SourceRow key={source.title} source={source} />)}
          </ul>
        </section>
      ))}
      <section className="rounded-xl border border-line bg-white p-4">
        <h2 className="mb-1 font-bold">시설 공공데이터</h2>
        <ul>
          {places.map((s) => (
            <SourceRow
              key={s.kind}
              source={{ title: s.title, publisher: `${s.label} · 데이터 기준 ${s.updated.slice(0, 10)}`, url: s.url, use: "시설 찾기", scale: `${s.rows.toLocaleString()}곳` }}
            />
          ))}
        </ul>
      </section>
      <p className="text-xs text-muted">
        이 프로젝트는 AI Hub(aihub.or.kr)의 「반려견 성장 및 질병관련 말뭉치 데이터」를 활용했습니다. 이 데이터는 과학기술정보통신부와 한국지능정보사회진흥원의
        사업 결과입니다. 자세한 이용 조건과 가공 방법은{" "}
        <a href={DOC("docs/data-sources.md")} target="_blank" rel="noreferrer" className="underline">데이터 명세서</a>에 있습니다.
      </p>
    </div>
  );
}
