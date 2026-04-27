# AeroMind Compliance - GCP Deployment Script (Sprint 8)
# DO-326A / EASA Certifiable Infrastructure

$PROJECT_ID = "regumap-ai-493622"
$REGION = "europe-west1"
$REPO_NAME = "aeromind-repo"

Write-Host "🚀 Starting GCP Deployment for AeroMind Compliance..." -ForegroundColor Cyan

# 1. Configuration du Projet
Write-Host "Step 1: Setting project to $PROJECT_ID..."
cmd /c gcloud config set project $PROJECT_ID

# 2. Activation des APIs (Nécessite Billing activé)
Write-Host "Step 2: Enabling required APIs..."
cmd /c gcloud services enable artifactregistry.googleapis.com `
                         run.googleapis.com `
                         vpcaccess.googleapis.com `
                         compute.googleapis.com

# 3. Création du Registre d'Artéfacts
Write-Host "Step 3: Creating Artifact Registry..."
cmd /c gcloud artifacts repositories create $REPO_NAME `
    --repository-format=docker `
    --location=$REGION `
    --description="Docker repository for AeroMind Compliance production images"

# 4. Build & Push (Remote via Cloud Build)
# Cette méthode évite de dépendre d'un daemon Docker local
Write-Host "Step 4: Building and Pushing images via Cloud Build..."

$IMAGES = @("backend", "gateway", "frontend")

foreach ($IMG in $IMAGES) {
    Write-Host "Building aeromind-$IMG..."
    cmd /c gcloud builds submit "./$IMG" --tag "$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/aeromind-$IMG:latest"
}

Write-Host "✅ T8.1 Complete: Images are now in the Artifact Registry." -ForegroundColor Green
