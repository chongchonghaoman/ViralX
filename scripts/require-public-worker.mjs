const rawUrl = String(process.env.VIRALX_PUBLIC_API_BASE_URL || "").trim();

if (!rawUrl) {
  throw new Error(
    "Production deploy requires VIRALX_PUBLIC_API_BASE_URL so EdgeOne can relay short analysis-job requests to the Worker.",
  );
}

const workerUrl = new URL(rawUrl);
if (
  workerUrl.protocol !== "https:"
  || workerUrl.username
  || workerUrl.password
  || workerUrl.search
  || workerUrl.hash
) {
  throw new Error("VIRALX_PUBLIC_API_BASE_URL must be a credential-free HTTPS root URL.");
}

console.log("Production analysis Worker:", workerUrl.origin);
