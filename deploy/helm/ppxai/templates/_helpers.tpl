{{/*
Expand the name of the chart.
*/}}
{{- define "ppxai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
App prefix — used for K8s resource naming.
Defaults to appPrefix value, or release-chart if unset.
*/}}
{{- define "ppxai.fullname" -}}
{{- .Values.appPrefix | default (printf "%s-%s" .Release.Name (include "ppxai.name" .)) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Namespace for all resources.
*/}}
{{- define "ppxai.namespace" -}}
{{- .Values.namespace }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "ppxai.labels" -}}
app.kubernetes.io/name: {{ include "ppxai.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{/*
Selector labels for matching pods to deployments/services.
*/}}
{{- define "ppxai.selectorLabels" -}}
app.kubernetes.io/name: {{ include "ppxai.fullname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Registry wait init-container command.
*/}}
{{- define "ppxai.registryWaitCommand" -}}
{{- if .Values.registry.external -}}
until nc -z {{ .Values.registry.externalHost }} {{ .Values.registry.externalPort | default 5000 }}; do echo "waiting for registry..."; sleep 3; done
{{- else -}}
until nc -z registry.{{ include "ppxai.namespace" . }}.svc {{ .Values.registry.port | default 5000 }}; do echo "waiting for registry..."; sleep 3; done
{{- end -}}
{{- end }}

{{/*
Full registry URL for Kaniko destinations and image references.
*/}}
{{- define "ppxai.registryUrl" -}}
{{- if .Values.registry.external -}}
{{- .Values.registry.externalHost }}:{{ .Values.registry.externalPort | default 5000 }}
{{- else -}}
registry.{{ include "ppxai.namespace" . }}.svc:{{ .Values.registry.port | default 5000 }}
{{- end -}}
{{- end }}

{{/*
Registry URL for image pulls (kubelet perspective).
On microk8s, kubelet can't resolve in-cluster DNS — it uses localhost:32000.
Falls back to registryUrl if pullHost is not set.
*/}}
{{- define "ppxai.registryPullUrl" -}}
{{- if .Values.registry.pullHost -}}
{{- .Values.registry.pullHost }}
{{- else -}}
{{- include "ppxai.registryUrl" . }}
{{- end -}}
{{- end }}

{{/*
Server image full reference (for kubelet image pull).
*/}}
{{- define "ppxai.serverImage" -}}
{{ include "ppxai.registryPullUrl" . }}/{{ include "ppxai.fullname" . }}-server:{{ .Values.image.tag }}
{{- end }}

{{/*
Session manager image full reference (for kubelet image pull).
*/}}
{{- define "ppxai.sessionManagerImage" -}}
{{ include "ppxai.registryPullUrl" . }}/{{ include "ppxai.fullname" . }}-session-manager:{{ .Values.image.tag }}
{{- end }}

{{/*
Ingress name.
*/}}
{{- define "ppxai.ingressName" -}}
{{ include "ppxai.fullname" . }}-ingress
{{- end }}
