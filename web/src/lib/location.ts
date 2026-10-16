// "현재 위치 사용": the browser's position, asked only when the guardian clicks
// (src/location_component.py). Kept in this tab's memory only, never stored.

export type Location = [number, number];

const MESSAGES: Record<string, string> = {
  denied: "위치 권한이 거부되었습니다.",
  timeout: "위치 요청 시간이 초과되었습니다.",
  unsupported: "브라우저에서 위치 기능을 지원하지 않습니다.",
  insecure: "위치 기능은 HTTPS 환경에서 사용할 수 있습니다.",
  unavailable: "현재 위치를 가져오지 못했습니다.",
  outside: "유효하지 않은 위치입니다.",
};

/** The position when it is in Korea (where the places data is), else why not. */
export function checkPosition(latitude: number, longitude: number): { location: Location } | { error: string } {
  if (!(latitude >= 33 && latitude <= 39 && longitude >= 124 && longitude <= 132)) return { error: MESSAGES.outside };
  return { location: [latitude, longitude] };
}

export function locate(): Promise<{ location: Location } | { error: string }> {
  if (!window.isSecureContext) return Promise.resolve({ error: MESSAGES.insecure });
  if (!navigator.geolocation) return Promise.resolve({ error: MESSAGES.unsupported });
  return new Promise((resolve) =>
    navigator.geolocation.getCurrentPosition(
      (position) => resolve(checkPosition(position.coords.latitude, position.coords.longitude)),
      (error) => resolve({ error: MESSAGES[error.code === 1 ? "denied" : error.code === 3 ? "timeout" : "unavailable"] }),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 },
    ),
  );
}
