# Proofed

[English](README.md) | [简体中文](README.zh-CN.md)

### 不要问 Agent 是否完成，问当前代码有没有证据。

编码 Agent 可能在没有证据时宣布“完成”。Proofed 会拒绝 `PASSED`，直到**当前代码**具备仓库要求的证据，并写出可携带的完成回执。

[![真实运行：REJECT、PASSED、独立校验，随后 STALE_SUBJECT](assets/proofed-red-green.gif)](assets/proofed-red-green.mp4)

## 安装完成闸门 Skill

```bash
npx skills add liangfeng-hu/proofed --skill proofed-verify
```

Skill 挂在已有编码 Agent 上，不替代 Agent。请从 PyPI 安装零运行时依赖的发行包：

```bash
python -m pip install proofed-agent
```

## 看一次假完成被拒绝

```console
$ proofed verify
REJECT: missing tests_passed
$ proofed verify --run-tests
PASSED: current code has all required evidence
$ proofed check-receipt RECEIPT --current .
VALID: PASSED receipt matches current subject
```

之后改动一个字节，旧回执就会被拒绝为 `STALE_SUBJECT`。[完整红/绿演示](examples/false-completion)约 30 秒。

## 这份回执为什么不同

- **可携带：** Python 和 JavaScript 校验器无需 Proofed 内核、状态数据库或本机密钥即可读取。
- **绑定当前对象：** 代码变化后，旧回执立即过期。
- **CI 不信任仓库里的 PASS 文件：** Action 会对当前 checkout 重新执行已配置检查。

## 在仓库中使用

```bash
proofed init
proofed run . --intent "完成当前仓库任务"
proofed status
proofed verify --run-tests
```

`proofed init` 是仓库级显式启用。当前自动识别 `pytest`、`unittest` 和 `npm test`。

把同一闸门加入 PR：

```yaml
- uses: liangfeng-hu/proofed@v0.1.0-alpha.1
  with:
    target: .
```

## Alpha 边界

Proofed v0.1-alpha 已实现证据门控完成和对象过期拒绝，但不声称生产闭环、外部副作用的通用 exactly-once、不可绕过的宿主 Hook，或“测试通过即软件正确”。CI 是更强的约束面。
