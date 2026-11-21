// Software Factory gate (E07). Rendered by `python install.py ci jenkins`; upgrades re-render it.
// Turn it on: point a Pipeline or Multibranch job's script path at this file.
// The agent needs Python 3.12, uv (Python projects with uv.lock) and Node
// (TS/JS projects) on PATH, and runs sh steps, so use a Linux or macOS agent.
pipeline {
    agent any
    stages {
        stage('Setup') {
            steps {
            sh 'command -v python3 >/dev/null || { echo "factory-gate: Python 3.12 is not on this agent" >&2; exit 1; }'
            sh 'command -v uv >/dev/null || { echo "factory-gate: uv is not on this agent" >&2; exit 1; }'
            sh 'command -v npm >/dev/null || { echo "factory-gate: Node (npm) is not on this agent" >&2; exit 1; }'
            sh 'git rev-parse --is-shallow-repository | grep -q true && git fetch --unshallow || true'
            sh 'uv sync --locked'
            sh 'npm ci'
            }
        }
        stage('Gate') {
            when {
                anyOf {
                    changeRequest()
                    branch 'develop'
                }
            }
            steps {
                script {
                    if (env.CHANGE_TARGET) {
                        sh "git fetch origin ${env.CHANGE_TARGET}"
                        sh "uv run python .factory/gates/gate.py --base-ref origin/${env.CHANGE_TARGET}"
                    } else {
                        sh 'uv run python .factory/gates/gate.py'
                    }
                }
            }
        }
    }
}
