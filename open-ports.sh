#!/bin/bash

echo "=== Opening Ports for Container Service ==="
echo ""
echo "This script will open the necessary ports for the container service"
echo "You need to run this as root (sudo)"
echo ""

if [ "$EUID" -eq 0 ]; then
    echo "✅ Running as root, opening ports..."
    
    # Open port 3000 (main service)
    ufw allow 3000/tcp
    echo "✅ Opened port 3000 (HTTP service)"
    
    # Open port 3443 (HTTPS service)  
    ufw allow 3443/tcp
    echo "✅ Opened port 3443 (HTTPS service)"
    
    # Open standard ports
    ufw allow 80/tcp
    echo "✅ Opened port 80 (standard HTTP)"
    
    ufw allow 443/tcp
    echo "✅ Opened port 443 (standard HTTPS)"
    
    # Show firewall status
    echo ""
    echo "🔥 Current firewall status:"
    ufw status numbered
    
    echo ""
    echo "🎉 Ports opened! Your container service should now be accessible at:"
    echo "   http://containers.conflost.com:3000"
    echo "   https://containers.conflost.com:3443"
    
else
    echo "⚠️  This script needs to run as root to modify firewall rules"
    echo ""
    echo "Run: sudo ./open-ports.sh"
    echo ""
    echo "Or manually:"
    echo "sudo ufw allow 3000/tcp"
    echo "sudo ufw allow 3443/tcp" 
    echo "sudo ufw allow 80/tcp"
    echo "sudo ufw allow 443/tcp"
fi