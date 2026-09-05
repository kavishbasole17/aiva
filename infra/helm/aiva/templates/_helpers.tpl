{{- define "aiva.fullname" -}}
{{ .Release.Name }}-aiva
{{- end -}}

{{- define "aiva.labels" -}}
app.kubernetes.io/part-of: aiva
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "aiva.componentLabels" -}}
{{ include "aiva.labels" . }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "aiva.image" -}}
{{- if .root.Values.image.registry -}}
{{ .root.Values.image.registry }}/aiva-{{ .name }}:{{ .root.Values.image.tag }}
{{- else -}}
aiva-{{ .name }}:{{ .root.Values.image.tag }}
{{- end -}}
{{- end -}}
