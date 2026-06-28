const SPACE_API_URL = "https://huggingface.co/api/spaces/qiyan456/wc2026-dashboard";

export async function collectHfSpaceMetadata(fetchImpl = globalThis.fetch) {
  const response = await fetchImpl(SPACE_API_URL, {
    headers: { accept: "application/json" }
  });
  if (!response.ok) {
    throw new Error(`Hugging Face Space metadata failed: ${response.status}`);
  }

  const payload = await response.json();
  return {
    source: "huggingface-space",
    id: payload.id ?? "qiyan456/wc2026-dashboard",
    sha: payload.sha ?? null,
    lastModified: payload.lastModified ?? null,
    sdk: payload.sdk ?? payload.cardData?.sdk ?? null,
    stage: payload.runtime?.stage ?? null,
    host: payload.host ?? payload.runtime?.host ?? "https://qiyan456-wc2026-dashboard.hf.space",
    url: "https://huggingface.co/spaces/qiyan456/wc2026-dashboard"
  };
}
