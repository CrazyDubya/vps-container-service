#!/bin/bash

# Container Service - Image Pre-download Script
# This script downloads all base images used by templates to ensure
# fast container creation out of the box

echo "🚀 Container Service - Pre-downloading base images..."
echo "This will download all images used by templates for faster container creation."
echo ""

# Array of images to download
declare -a IMAGES=(
    "ubuntu:22.04"
    "alpine:latest"
    "python:3.11-slim"
    "node:20-slim"
    "golang:1.21-alpine"
    "rust:1.75-slim"
    "openjdk:21-slim"
    "nginx:alpine"
    "httpd:2.4-alpine"
    "postgres:15-alpine"
    "redis:7-alpine"
    "pytorch/pytorch:latest"
    "tensorflow/tensorflow:latest"
)

# LXD images that need special handling
declare -a LXD_IMAGES=(
    "ubuntu:22.04"
    "images:alpine/3.18"
)

# Function to check if running with LXD
check_lxd() {
    if command -v lxc &> /dev/null; then
        echo "✅ LXD detected"
        return 0
    else
        echo "❌ LXD not found"
        return 1
    fi
}

# Function to check if running with Docker
check_docker() {
    if command -v docker &> /dev/null; then
        echo "✅ Docker detected"
        return 0
    else
        echo "❌ Docker not found"
        return 1
    fi
}

# Pre-download LXD images
download_lxd_images() {
    echo ""
    echo "📦 Pre-downloading LXD images..."
    
    for image in "${LXD_IMAGES[@]}"; do
        echo -n "  Downloading $image... "
        
        # Check if image already exists
        if lxc image list | grep -q "${image}"; then
            echo "✅ Already cached"
        else
            # Download the image
            if lxc image copy "${image}" local: --auto-update 2>/dev/null; then
                echo "✅ Downloaded"
            else
                echo "❌ Failed"
            fi
        fi
    done
}

# Pre-download Docker images
download_docker_images() {
    echo ""
    echo "🐳 Pre-downloading Docker images..."
    
    for image in "${IMAGES[@]}"; do
        echo -n "  Pulling $image... "
        
        # Pull the image
        if docker pull "${image}" > /dev/null 2>&1; then
            echo "✅ Downloaded"
        else
            echo "❌ Failed"
        fi
    done
}

# Create a test container for each template to ensure full setup
test_templates() {
    echo ""
    echo "🧪 Testing template initialization..."
    
    # Test with a simple Ubuntu container
    if check_lxd; then
        echo -n "  Testing LXD container creation... "
        
        # Create and delete a test container
        if lxc launch ubuntu:22.04 cf-test-setup --ephemeral > /dev/null 2>&1; then
            sleep 2
            lxc delete cf-test-setup --force > /dev/null 2>&1
            echo "✅ Success"
        else
            echo "❌ Failed"
        fi
    fi
}

# Main execution
echo "🔍 Detecting container runtime..."

if check_lxd; then
    download_lxd_images
    test_templates
elif check_docker; then
    download_docker_images
else
    echo ""
    echo "⚠️  No container runtime detected!"
    echo "Please install either LXD or Docker first."
    exit 1
fi

echo ""
echo "✅ Image pre-download complete!"
echo ""
echo "📌 Quick Start:"
echo "  1. Start the service: npm start"
echo "  2. Access at: http://localhost:3000"
echo "  3. Default admin: admin / admin123"
echo ""
echo "Containers will now create much faster with pre-cached images! 🚀"