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
            sh 'git rev-parse --is-shallow-repository | grep -q true && git fetch --unshallow || true'
            sh 'python3 -m pip install -e .'
            }
        }
        stage('Gate') {
            when {
                anyOf {
                    changeRequest()
                    branch 'main'
                }
            }
            steps {
                script {
                    if (env.CHANGE_TARGET) {
                        sh "git fetch origin ${env.CHANGE_TARGET}"
                        sh "python .factory/gates/gate.py --base-ref origin/${env.CHANGE_TARGET}"
                    } else {
                        sh 'python .factory/gates/gate.py'
                    }
                }
            }
        }
    }
}
