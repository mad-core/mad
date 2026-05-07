# CHANGELOG


## v0.5.0 (2026-05-07)

_No consumer-visible changes. Internal `sessions` work — see git history._


## v0.4.0 (2026-05-07)

### Bug Fixes

- **http**: Type request bodies with Pydantic and tolerate invalid Last-Event-ID
  ([`fe0f8c3`](https://github.com/jlsaco/mad/commit/fe0f8c3b8a2628eecb3d32cd40a2015c3f0e25e9))

### Features

- **api**: Add /v1/events and /v1/events/stream endpoints
  ([`5b5bdc1`](https://github.com/jlsaco/mad/commit/5b5bdc186001e93518b578530e78e9e0e5634918))


## v0.3.0 (2026-05-04)

### Bug Fixes

- Include use_cases/sessions/ files missed by gitignore
  ([`c04c318`](https://github.com/jlsaco/mad/commit/c04c318c9d15399c5f277918ef683e0c0ea9d631))
- **makefile**: Point serve target at the new adapters path
  ([`846274c`](https://github.com/jlsaco/mad/commit/846274ca2222a0dae2475aac676cd8923784666d))

### Features

- **api**: Inject launcher_factory and relocate test doubles
  ([`3c4f322`](https://github.com/jlsaco/mad/commit/3c4f322a0f29e3b04da0c4e14997a0c81ad1d449))


## v0.2.0 (2026-04-30)

### Features

- **claude-cli**: Implement ClaudeCLI provider with timeout and cancellation
  ([`96ecfe3`](https://github.com/jlsaco/mad/commit/96ecfe31dbe98482cfbfe8730aee6bbe2c687ecf))
- **infra**: Realign codebase to infrastructure-only architecture
  ([`7471cb1`](https://github.com/jlsaco/mad/commit/7471cb13abebc182ad9d279944ad22ca3569a92c))


## v0.1.0 (2026-04-15)

### Build System

- **pypi**: Rename package to mad-bros
  ([`fbb828c`](https://github.com/jlsaco/mad/commit/fbb828cc0e8501fa846725bb1d2d430cecc479e4))

### Features

- Initialize project infrastructure for Mad v0.1
  ([`1494569`](https://github.com/jlsaco/mad/commit/1494569f02344b9b0a923446f765801e37f728ec))
- **api**: Implement session management and provider interfaces
  ([`b232a75`](https://github.com/jlsaco/mad/commit/b232a756af10e05e32bfd8e635380bdb3f6c2aff))
