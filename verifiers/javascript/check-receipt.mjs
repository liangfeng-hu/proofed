#!/usr/bin/env node
// Kernel-free SRR verifier. Uses only Node.js built-ins.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const STATEMENT_TYPE = "https://in-toto.io/Statement/v1";
const TEST_RESULT_TYPE = "https://in-toto.io/attestation/test-result/v0.1";
const COMPLETION_TYPE = "urn:uuid:7ec9a0e8-9d21-4b8c-9bdd-11e1ab3c87cf";
const IGNORED = new Set([".git", ".proofed", ".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__", "node_modules"]);

function canonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  throw new Error("unsupported canonical JSON value");
}

function digest(value) {
  return crypto.createHash("sha256").update(canonical(value), "utf8").digest("hex");
}

function fileDigest(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function ignored(relative) {
  return relative.split(/[\\/]/).some((part) => IGNORED.has(part));
}

function compareUtf8(left, right) {
  return Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"));
}

function entry(root, relative) {
  const absolute = path.join(root, relative);
  const stats = fs.lstatSync(absolute);
  const normalized = relative.split(path.sep).join("/");
  if (stats.isSymbolicLink()) return { path: normalized, symlink: fs.readlinkSync(absolute) };
  if (stats.isFile()) return { path: normalized, sha256: fileDigest(absolute) };
  return { path: normalized, kind: "non-regular" };
}

function walk(root, current = root, result = []) {
  for (const item of fs.readdirSync(current, { withFileTypes: true })) {
    const absolute = path.join(current, item.name);
    const relative = path.relative(root, absolute);
    if (ignored(relative)) continue;
    if (item.isDirectory()) walk(root, absolute, result);
    else result.push(relative);
  }
  return result;
}

function git(root, args, binary = false) {
  const result = spawnSync("git", ["-C", root, ...args], { encoding: binary ? null : "utf8" });
  if (result.status !== 0) throw new Error(String(result.stderr || "git failed").trim());
  return binary ? result.stdout : result.stdout.trim();
}

function currentSubject(rootValue) {
  const root = path.resolve(rootValue);
  let inside = false;
  try { inside = git(root, ["rev-parse", "--is-inside-work-tree"]) === "true"; } catch {}
  let descriptor;
  if (!inside) {
    const entries = walk(root).sort(compareUtf8).map((name) => entry(root, name));
    descriptor = { descriptorVersion: "0.1", commitOid: null, treeOid: null, workspacePatchSha256: digest({ entries }) };
  } else {
    let commit = null;
    let tree = null;
    let patchBytes = Buffer.alloc(0);
    try {
      commit = git(root, ["rev-parse", "HEAD"]);
      tree = git(root, ["rev-parse", "HEAD^{tree}"]);
      patchBytes = git(root, ["diff", "--binary", "--no-ext-diff", "HEAD", "--", ".", ":(exclude).proofed/**", ":(exclude)**/__pycache__/**", ":(exclude).pytest_cache/**", ":(exclude)node_modules/**"], true);
    } catch {}
    const raw = git(root, ["ls-files", "--others", "--exclude-standard", "-z"], true);
    const names = raw.toString("utf8").split("\0").filter((name) => name && !ignored(name)).sort(compareUtf8);
    const untracked = names.map((name) => entry(root, name));
    const patchDescriptor = { trackedPatchSha256: crypto.createHash("sha256").update(patchBytes).digest("hex"), untracked };
    descriptor = { descriptorVersion: "0.1", commitOid: commit, treeOid: tree, workspacePatchSha256: digest(patchDescriptor) };
  }
  return digest(descriptor);
}

function verify(bundle, expectedSubject = null, requireTrust = null) {
  if (!bundle || typeof bundle !== "object" || bundle.bundleVersion !== "0.1") return ["UNSUPPORTED_BUNDLE_VERSION"];
  if (!Array.isArray(bundle.statements)) return ["MISSING_STATEMENTS"];
  const completions = bundle.statements.filter((item) => item && item.predicateType === COMPLETION_TYPE);
  const tests = bundle.statements.filter((item) => item && item.predicateType === TEST_RESULT_TYPE);
  if (completions.length !== 1) return ["EXPECTED_ONE_COMPLETION_STATEMENT"];
  const completion = completions[0];
  const errors = [];
  if (completion._type !== STATEMENT_TYPE) errors.push("INVALID_STATEMENT_TYPE");
  if (!Array.isArray(completion.subject) || completion.subject.length !== 1) return [...errors, "INVALID_SUBJECT"].sort();
  const subjectDigest = completion.subject[0]?.digest?.sha256;
  if (typeof subjectDigest !== "string" || subjectDigest.length !== 64) errors.push("INVALID_SUBJECT_DIGEST");
  if (expectedSubject && subjectDigest !== expectedSubject.replace(/^sha256:/, "")) errors.push("STALE_SUBJECT");
  const predicate = completion.predicate;
  if (!predicate || typeof predicate !== "object" || predicate.schemaVersion !== "0.1") return [...new Set([...errors, "INVALID_COMPLETION_PREDICATE"])].sort();
  const descriptor = predicate.subjectDescriptor;
  if (!descriptor || typeof descriptor !== "object" || digest(descriptor) !== subjectDigest) errors.push("SUBJECT_DESCRIPTOR_MISMATCH");
  const ranks = { L0: 0, L1: 1, L2: 2 };
  const trust = predicate.producer?.trustLevel;
  if (!(trust in ranks)) errors.push("INVALID_TRUST_LEVEL");
  if (requireTrust === "L1" || requireTrust === "L2") errors.push("UNVERIFIED_TRUST_CLAIM");
  let required = predicate.requiredEvidence;
  let missing = predicate.missingEvidence;
  if (!Array.isArray(required) || !Array.isArray(missing)) {
    errors.push("INVALID_EVIDENCE_LISTS"); required = []; missing = [];
  }
  if (predicate.decision !== "PASSED") errors.push("COMPLETION_NOT_PASSED");
  if ((predicate.decision === "PASSED") !== (predicate.phase === "PASSED")) errors.push("DECISION_PHASE_MISMATCH");
  if (missing.length) errors.push("MISSING_REQUIRED_EVIDENCE");
  const testMap = new Map(tests.map((item) => [digest(item), item]));
  const referenced = [];
  let refs = predicate.evidenceRefs;
  if (!Array.isArray(refs)) { errors.push("INVALID_EVIDENCE_REFS"); refs = []; }
  for (const ref of refs) {
    if (ref?.predicateType !== TEST_RESULT_TYPE) continue;
    const target = String(ref.digest || "").replace(/^sha256:/, "");
    if (!testMap.has(target)) errors.push("BROKEN_EVIDENCE_REFERENCE");
    else referenced.push(testMap.get(target));
  }
  if (required.includes("tests_passed")) {
    if (!referenced.length) errors.push("MISSING_TEST_RESULT");
    for (const statement of referenced) {
      const testPredicate = statement.predicate || {};
      if (statement._type !== STATEMENT_TYPE) errors.push("INVALID_TEST_STATEMENT_TYPE");
      if (canonical(statement.subject) !== canonical(completion.subject)) errors.push("TEST_SUBJECT_MISMATCH");
      if (testPredicate.result !== "PASSED" || (Array.isArray(testPredicate.failedTests) && testPredicate.failedTests.length)) errors.push("TEST_RESULT_NOT_PASSED");
      let configurations = testPredicate.configuration;
      if (!Array.isArray(configurations) || !configurations.length) { errors.push("MISSING_TEST_CONFIGURATION"); configurations = []; }
      const actual = configurations.filter((item) => item && typeof item === "object").map((item) => item.digest?.sha256).sort();
      const expected = [...(predicate.policy?.testConfigurationDigests || [])].sort();
      if (canonical(actual) !== canonical(expected)) errors.push("TEST_CONFIGURATION_MISMATCH");
    }
  }
  if (required.includes("git_diff_recorded") && (!descriptor || !descriptor.workspacePatchSha256)) errors.push("MISSING_GIT_DIFF_EVIDENCE");
  if (required.some((item) => !["tests_passed", "git_diff_recorded"].includes(item))) errors.push("UNKNOWN_REQUIRED_EVIDENCE");
  if (!Array.isArray(predicate.effects)) errors.push("INVALID_EFFECTS");
  else for (const effect of predicate.effects) if (effect?.state === "EFFECT_UNKNOWN" && effect.retryAllowed === true) errors.push("UNKNOWN_EFFECT_RETRY_ALLOWED");
  if (predicate.policy?.evidenceDegradedByUser === true && !predicate.policy?.degradationAuthorization) errors.push("UNAUTHORIZED_EVIDENCE_DEGRADATION");
  return [...new Set(errors)].sort();
}

function usage() {
  console.error("usage: check-receipt.mjs INPUT [--current PROJECT|--subject SHA256] [--require-trust L0|L1|L2] [--vectors]");
}

const args = process.argv.slice(2);
if (!args.length) { usage(); process.exit(2); }
const input = args[0];
const option = (name) => { const index = args.indexOf(name); return index >= 0 ? args[index + 1] : null; };
const data = JSON.parse(fs.readFileSync(input, "utf8"));
if (args.includes("--vectors")) {
  const failures = [];
  for (const item of data.cases || []) {
    const actual = verify(item.bundle);
    const expected = [...item.expectedErrors].sort();
    if (canonical(actual) !== canonical(expected)) failures.push({ name: item.name, expected, actual });
  }
  if (failures.length) { console.error(JSON.stringify(failures, null, 2)); process.exit(1); }
  console.log(`PASS: ${(data.cases || []).length} conformance vectors`);
  process.exit(0);
}
let expected = option("--subject");
const current = option("--current");
if (current) expected = currentSubject(current);
const errors = verify(data, expected, option("--require-trust"));
if (errors.length) { console.error(`INVALID: ${errors.join(", ")}`); process.exit(4); }
console.log("VALID: completion receipt passed independent checks");
