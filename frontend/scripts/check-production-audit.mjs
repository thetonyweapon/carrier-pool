import { readFile } from "node:fs/promises";

const reportPath = process.argv[2];
const report = JSON.parse(await readFile(reportPath, "utf8"));
const allowedAdvisory = "GHSA-qwww-vcr4-c8h2";
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

if (findings.length > 0) {
  console.warn(
    `Allowed upstream advisory remains unresolved: ${allowedAdvisory}. ` +
      "Revisit when a patched React Router release is published.",
  );
}
