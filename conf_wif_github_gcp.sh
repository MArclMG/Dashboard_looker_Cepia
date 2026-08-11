#!/bin/bash

# ==========================================
# CONFIGURACIÓN ESPECÍFICA DE ESTE PROYECTO
# ==========================================
PROJECT_ID="dashboardlookercepia"    # Ej: mi-proyecto-grafo-123456
REPO_GITHUB="MArclMG/Dashboard_looker_Cepia"       # Ej: mi-usuario/red-endosos
SA_NAME="githubbot"           # El nombre de la Service Account (sin el @domain) 

POOL_NAME="github-actions-pool"
PROVIDER_NAME="github-actions-provider"

echo "➡️ Iniciando configuración de WIF para el proyecto: $PROJECT_ID"

# 1. Habilitar las APIs necesarias en ESTE proyecto específico
gcloud services enable iamcredentials.googleapis.com cloudresourcemanager.googleapis.com \
  --project="$PROJECT_ID"

# 2. Crear el Workload Identity Pool
gcloud iam workload-identity-pools create "$POOL_NAME" \
  --project="$PROJECT_ID" \
  --location="global" \
  --description="Pool para GitHub Actions" \
  --display-name="GitHub Actions Pool"

# 3. Crear el Provider OIDC dentro del Pool
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_NAME" \
  --project="$PROJECT_ID" \
  --location="global" \
  --workload-identity-pool="$POOL_NAME" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '$REPO_GITHUB'"

# 4. Obtener el número de proyecto y el correo completo de la Service Account
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# 5. Otorgar permisos a GitHub sin tocar la configuración global
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_NAME/attribute.repository/$REPO_GITHUB"

# 6. Imprimir los valores exactos que debes copiar a GitHub Secrets
echo ""
echo "=========================================================="
echo "✅ ¡CONFIGURACIÓN COMPLETADA CON ÉXITO!"
echo "Copia estos dos valores en Settings > Secrets > Actions:"
echo "=========================================================="
echo "Nombre del Secret: GCP_WORKLOAD_IDENTITY_PROVIDER"
echo "Valor: projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL_NAME/providers/$PROVIDER_NAME"
echo "----------------------------------------------------------"
echo "Nombre del Secret: GCP_SERVICE_ACCOUNT"
echo "Valor: $SA_EMAIL"
echo "=========================================================="