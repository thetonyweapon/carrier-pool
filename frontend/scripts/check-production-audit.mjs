import { readFile } from "node:fs/promises";

const reportPath = process.argv[2];
const auditStatus = Number(process.argv[3] ?? "0");
const report = JSON.parse(await readFile(reportPath, "utf8"));
const allowedAdvisory = "GHSA-qwww-vcr4-c8h2";
if (report.error) {
  console.error(`npm audit failed: ${report.error.code ?? "unknown error"}`);
  process.exit(1);
}
const findings = Object.values(report.vulnerabilities ?? {}).flatMap((vulnerability) =>
  vulnerability.via.filter((item) => typeof item === "object"),
);
const unexpected = findings.filter((finding) => !finding.url?.includes(allowedAdvisory));

if (unexpected.length > 0) {
  console.error("Unexpected production dependency advisories:");
  for (const finding of unexpected) {
    console.error(`- ${finding.name}: ${finding.url}`);
  }
  process.exit(1);
}

if (auditStatus !== 0 && auditStatus !== 1) {
  console.error(`npm audit exited with unexpected status ${auditStatus}`);
  process.exit(1);
}

if (auditStatus !== 0 && findings.length === 0) {
  console.error("npm audit failed without a vulnerability report");
  process.exit(1);
}

if (findings.length > 0) {
  console.warn(
    `Allowed upstream advisory remains unresolved: ${allowedAdvisory}. ` +
      "Revisit when a patched React Router release is published.",
  );
}
