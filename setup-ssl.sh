#!/bin/bash

echo "=== SSL Certificate Setup for containers.conflost.com ==="
echo ""
echo "The domain containers.conflost.com is working! Here's how to get proper SSL:"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    echo "✅ Running as root, proceeding with automatic setup..."
    
    # Install certbot if not present
    if ! command -v certbot &> /dev/null; then
        echo "📦 Installing certbot..."
        apt-get update
        apt-get install -y certbot
    fi
    
    # Stop any service on port 80 temporarily
    echo "🔄 Temporarily stopping services on port 80..."
    fuser -k 80/tcp 2>/dev/null || true
    
    # Get certificate
    echo "🔐 Obtaining SSL certificate..."
    certbot certonly --standalone -d containers.conflost.com --non-interactive --agree-tos --email admin@conflost.com
    
    if [ $? -eq 0 ]; then
        echo "✅ Certificate obtained successfully!"
        
        # Copy certificates to project directory
        cp /etc/letsencrypt/live/containers.conflost.com/fullchain.pem ./server.crt
        cp /etc/letsencrypt/live/containers.conflost.com/privkey.pem ./server.key
        
        # Set proper permissions
        chown stephen:stephen ./server.crt ./server.key
        chmod 600 ./server.key
        chmod 644 ./server.crt
        
        echo "✅ Certificates copied to project directory"
        echo "🔄 Restarting container service..."
        
        # Restart the service
        systemctl restart container-service 2>/dev/null || {
            echo "ℹ️  Please restart the container service manually"
        }
        
        echo ""
        echo "🎉 SSL setup complete!"
        echo "🌐 Access your service at: https://containers.conflost.com:3443"
        
    else
        echo "❌ Certificate generation failed"
        echo "   Make sure:"
        echo "   - Domain points to this server"
        echo "   - Port 80 is accessible from internet"
        echo "   - No firewall blocking connections"
    fi
    
else
    echo "⚠️  This script needs to run as root to obtain SSL certificates"
    echo ""
    echo "Run: sudo ./setup-ssl.sh"
    echo ""
    echo "Or manually:"
    echo "1. sudo certbot certonly --standalone -d containers.conflost.com"
    echo "2. sudo cp /etc/letsencrypt/live/containers.conflost.com/fullchain.pem ./server.crt"
    echo "3. sudo cp /etc/letsencrypt/live/containers.conflost.com/privkey.pem ./server.key"
    echo "4. sudo chown stephen:stephen ./server.crt ./server.key"
    echo "5. Restart the container service"
fi

echo ""
echo "Alternative: Use Cloudflare Origin Certificate"
echo "1. Cloudflare Dashboard > SSL/TLS > Origin Server"
echo "2. Create certificate for containers.conflost.com"
echo "3. Save as server.crt and server.key in this directory"