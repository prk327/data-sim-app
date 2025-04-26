{{/* Expand the name of the chart */}}
{{- define "data-simulator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name
*/}}
{{- define "data-simulator.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label
*/}}
{{- define "data-simulator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}


{{/*
Common labels
*/}}
{{- define "data-simulator.labels" -}}
helm.sh/chart: {{ include "data-simulator.chart" . }}
{{ include "data-simulator.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "data-simulator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "data-simulator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
ConfigMap name
*/}}
{{- define "data-simulator.configmapName" -}}
{{- printf "%s-config" (include "data-simulator.fullname" .) -}}
{{- end -}}

{{/* Volume mounts for config files */}}
{{- define "data-simulator.configVolumeMounts" -}}
- name: config-volume
  mountPath: /app/data_simulator/config/config.yaml
  subPath: config.yaml
  readOnly: true
{{- range $path := .Values.config.files.columns }}
- name: config-volume
  mountPath: /app/data_simulator/{{ $path }}
  subPath: {{ $path | base }}
  readOnly: true
{{- end }}
{{- range $path := .Values.config.files.tables }}
- name: config-volume
  mountPath: /app/data_simulator/{{ $path }}
  subPath: {{ $path | base }}
  readOnly: true
{{- end }}
{{- range $path := .Values.config.files.sql }}
- name: config-volume
  mountPath: /app/data_simulator/{{ $path }}
  subPath: {{ $path | base }}
  readOnly: true
{{- end }}
{{- end -}}

{{/* Check if folder mounting is enabled */}}
{{- define "data-simulator.mountFolders" -}}
{{- if .Values.config.mountFolders -}}
true
{{- end -}}
{{- end -}}

{{/* Get folder mount paths */}}
{{- define "data-simulator.configMountPath" -}}
{{- .Values.config.folderPaths.config -}}
{{- end -}}

{{- define "data-simulator.sqlMountPath" -}}
{{- .Values.config.folderPaths.sql -}}
{{- end -}}