#!/bin/bash

# Script Best Practices
set -e  # Exit immediately if a command exits with a non-zero status.
set -u  # Treat unset variables as an error when substituting.
set -o pipefail # The return value of a pipeline is the status of the last command to exit with a non-zero status, or zero if no command exited with a non-zero status.

# --- Helper Functions ---

# Define colors for output, if supported
if [ -t 1 ]; then
    BLUE='\033[0;34m'
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    NC='\033[0m' # No Color
else
    BLUE=''
    GREEN=''
    RED=''
    NC=''
fi

echoinfo() {
    echo -e "${GREEN}[INFO] ${1}${NC}"
}

echoerror() {
    echo -e "${RED}[ERROR] ${1}${NC}" >&2
    exit 1
}

OS_FAMILY="" # Will be 'debian' or 'rhel'

detect_os() {
    echoinfo "Detecting operating system..."
    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        if [[ "$ID_LIKE" == *"debian"* || "$ID" == "debian" || "$ID" == "ubuntu" ]]; then
            OS_FAMILY="debian"
            echoinfo "Debian-based OS detected (ID: $ID, ID_LIKE: $ID_LIKE)."
        elif [[ "$ID_LIKE" == *"rhel"* || "$ID_LIKE" == *"fedora"* || "$ID" == "centos" || "$ID" == "fedora" || "$ID" == "rhel" ]]; then
            OS_FAMILY="rhel"
            echoinfo "RHEL-based OS detected (ID: $ID, ID_LIKE: $ID_LIKE)."
            echoinfo "Full support is primarily for Debian/Ubuntu. Some steps might need manual adjustment for RHEL-based systems."
        else
            echoerror "Unsupported operating system (ID: $ID, ID_LIKE: $ID_LIKE). This script primarily supports Debian/Ubuntu and RHEL-based systems."
        fi
    elif [ -f /etc/debian_version ]; then
        OS_FAMILY="debian"
        echoinfo "Debian-based OS detected (found /etc/debian_version)."
    elif [ -f /etc/redhat-release ]; then
        OS_FAMILY="rhel"
        echoinfo "RHEL-based OS detected (found /etc/redhat-release)."
        echoinfo "Full support is primarily for Debian/Ubuntu. Some steps might need manual adjustment for RHEL-based systems."
    else
        echoerror "Could not detect OS type. This script primarily supports Debian/Ubuntu and RHEL-based systems."
    fi
}

check_command() {
    local command_name="$1"
    if command -v "$command_name" &>/dev/null; then
        return 0 # Command exists
    else
        return 1 # Command does not exist
    fi
}

install_packages() {
    local packages_to_install=("$@")
    if [ ${#packages_to_install[@]} -eq 0 ]; then
        echoinfo "No packages to install."
        return
    fi

    echoinfo "Attempting to install packages: ${packages_to_install[*]}"
    if [ "$OS_FAMILY" == "debian" ]; then
        echoinfo "Using apt-get for Debian-based system."
        sudo apt-get update -y || echoerror "apt-get update failed."
        # shellcheck disable=SC2068
        sudo apt-get install -y ${packages_to_install[@]} || echoerror "apt-get install failed for some packages."
    elif [ "$OS_FAMILY" == "rhel" ]; then
        echoinfo "Using yum/dnf for RHEL-based system."
        local pkg_manager=""
        if check_command dnf; then
            pkg_manager="dnf"
        elif check_command yum; then
            pkg_manager="yum"
        else
            echoerror "No DNF or YUM package manager found on this RHEL-based system."
        fi
        # shellcheck disable=SC2068
        sudo "$pkg_manager" install -y ${packages_to_install[@]} || echoerror "$pkg_manager install failed for some packages."
    else
        echoerror "Cannot install packages: Unsupported OS family '$OS_FAMILY'."
    fi
    echoinfo "Package installation attempt completed."
}

install_docker() {
    echoinfo "Checking Docker installation..."
    if check_command docker; then
        echoinfo "Docker is already installed. Version: $(docker --version)"
        # Optionally, ensure the docker service is running
        if ! sudo systemctl is-active --quiet docker; then
            echoinfo "Docker service is not running. Attempting to start it..."
            sudo systemctl start docker || echoerror "Failed to start docker service."
            sudo systemctl enable docker || echoinfo "Could not enable docker service to start on boot."
        fi
        return
    fi

    if [ "$OS_FAMILY" == "debian" ]; then
        echoinfo "Installing Docker Engine for Debian-based system..."
        # Add Docker's official GPG key:
        install_packages apt-transport-https ca-certificates
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg

        # Add the repository to Apt sources:
        # shellcheck disable=SC1091
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
          $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
          sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        
        install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        echoinfo "Verifying Docker installation..."
        if sudo docker run hello-world; then
            echoinfo "Docker installed and verified successfully."
        else
            echoerror "Docker verification (hello-world) failed."
        fi

        echoinfo "Adding current user ($USER) to the docker group..."
        sudo usermod -aG docker "$USER" || echoerror "Failed to add user to docker group."
        echoinfo "IMPORTANT: You may need to start a new shell session or re-login for the group changes to take effect."

    elif [ "$OS_FAMILY" == "rhel" ]; then
        echoinfo "Please ensure Docker Engine is installed on this RHEL-based system."
        echoinfo "You can follow the official Docker documentation: https://docs.docker.com/engine/install/centos/"
        # Consider adding a check here and exiting if Docker is not found after prompt.
    else
        echoerror "Docker installation not supported for OS family '$OS_FAMILY' by this script."
    fi
}

install_lxc() {
    echoinfo "Checking LXC installation..."
    if check_command lxc-checkconfig; then
        echoinfo "LXC appears to be installed. Running lxc-checkconfig..."
        sudo lxc-checkconfig || echoinfo "lxc-checkconfig reported some issues. Please review."
        return
    fi

    if [ "$OS_FAMILY" == "debian" ]; then
        echoinfo "Installing LXC for Debian-based system..."
        install_packages lxc lxc-templates
        
        echoinfo "Verifying LXC installation by running lxc-checkconfig..."
        sudo lxc-checkconfig || echoinfo "lxc-checkconfig reported some issues. Please review its output carefully."
        echoinfo "LXC installation attempt completed."

    elif [ "$OS_FAMILY" == "rhel" ]; then
        echoinfo "Please ensure LXC is installed on this RHEL-based system."
        echoinfo "Installation methods vary (e.g., EPEL repository). Refer to your distribution's documentation."
    else
        echoerror "LXC installation not supported for OS family '$OS_FAMILY' by this script."
    fi
}

setup_app_code() {
    local app_dir="$1"
    echoinfo "Setting up application code in $app_dir..."
    if [ ! -d "$app_dir" ]; then
        echoerror "Application directory $app_dir does not exist. This script assumes it is run from the repository root."
    fi
    echoinfo "Application directory is current directory: $app_dir"
    if [ ! -f "$app_dir/package.json" ] || [ ! -f "$app_dir/container-service.js" ]; then
        echoerror "Essential application files (package.json, container-service.js) not found in $app_dir. Ensure the script is run from the root of the cf-container-service repository."
    fi
}

install_app_dependencies() {
    local app_dir="$1"
    echoinfo "Installing application dependencies in $app_dir..."
    if [ ! -f "$app_dir/package.json" ]; then
        echoerror "package.json not found in $app_dir. Cannot install dependencies."
    fi
    
    cd "$app_dir" || echoerror "Failed to change directory to $app_dir"
    
    echoinfo "Running 'npm install --production'..."
    if npm install --production; then
        echoinfo "Application dependencies installed successfully."
    else
        echoerror "npm install failed. Please check for errors."
    fi
    # No need to cd back explicitly if script exits or APP_DIR is used consistently
}

configure_app() {
    local app_dir="$1"
    local env_file="$app_dir/.env"
    echoinfo "Configuring application (.env file) in $app_dir..."

    local api_key=""
    local jwt_secret=""
    local port="8082" # Default port
    local cf_team_domain=""
    local cf_audience_tag=""

    # API Key
    # shellcheck disable=SC2162
    read -p "Do you want to generate a new random API key for direct service access (e.g., for WebSockets)? (y/n, default: y): " generate_key_choice
    generate_key_choice=${generate_key_choice:-y} # Default to 'y' if empty

    if [[ "$generate_key_choice" == "y" || "$generate_key_choice" == "Y" ]]; then
        echoinfo "Generating random API key..."
        if check_command openssl; then
            api_key=$(openssl rand -hex 32)
        elif check_command node; then
            api_key=$(node -e "console.log(require('crypto').randomBytes(32).toString('hex'))")
        else
            echoerror "Cannot generate API key: openssl or node is required. Please install one or provide a key manually."
        fi
        echoinfo "Generated API Key: $api_key (This will be saved to .env)"
    else
        # shellcheck disable=SC2162
        read -p "Please enter your desired API key: " manual_api_key
        if [ -z "$manual_api_key" ]; then
            echoerror "API key cannot be empty."
        fi
        api_key="$manual_api_key"
    fi

    # Port
    # shellcheck disable=SC2162
    read -p "Enter port for the service (default: $port): " custom_port
    if [ -n "$custom_port" ]; then
        if ! [[ "$custom_port" =~ ^[0-9]+$ ]] || [ "$custom_port" -lt 1 ] || [ "$custom_port" -gt 65535 ]; then
            echoerror "Invalid port number: $custom_port. Must be between 1 and 65535."
        fi
        port="$custom_port"
    fi

    # JWT Secret
    # shellcheck disable=SC2162
    read -p "Do you want to generate a new random JWT Secret for user authentication? (y/n, default: y): " generate_jwt_choice
    generate_jwt_choice=${generate_jwt_choice:-y} # Default to 'y' if empty

    if [[ "$generate_jwt_choice" == "y" || "$generate_jwt_choice" == "Y" ]]; then
        echoinfo "Generating random JWT Secret..."
        if check_command openssl; then
            jwt_secret=$(openssl rand -hex 32)
        elif check_command node; then
            # Use a longer secret for JWT
            jwt_secret=$(node -e "console.log(require('crypto').randomBytes(64).toString('hex'))")
        else
            echoerror "Cannot generate JWT Secret: openssl or node is required. Please install one or provide a key manually."
        fi
        echoinfo "Generated JWT Secret: *** (hidden, will be saved to .env)"
    else
        # shellcheck disable=SC2162
        read -p "Please enter your desired JWT Secret (at least 32 characters long): " manual_jwt_secret
        if [ ${#manual_jwt_secret} -lt 32 ]; then # Basic length check
            echoerror "JWT Secret must be at least 32 characters long for security."
        fi
        jwt_secret="$manual_jwt_secret"
    fi
    
    # Cloudflare Access Configuration (Optional)
    echoinfo ""
    echoinfo "${BLUE}Cloudflare Access Integration (Optional):${NC}"
    echoinfo "If you plan to protect this service with Cloudflare Access, enter your Team Domain and Application Audience Tag."
    echoinfo "Leave these blank if you are not using Cloudflare Access for authentication."

    # shellcheck disable=SC2162
    read -p "Enter your Cloudflare Team Domain (e.g., your-team.cloudflareaccess.com, leave blank to skip): " cf_team_domain
    if [ -n "$cf_team_domain" ]; then
        # shellcheck disable=SC2162
        read -p "Enter your Cloudflare Application Audience Tag (AUD tag): " cf_audience_tag
        if [ -z "$cf_audience_tag" ]; then
            echoerror "Cloudflare Audience Tag cannot be empty if Team Domain is provided."
        fi
    else
        echoinfo "Skipping Cloudflare Access configuration."
        cf_audience_tag="" # Ensure it's empty if domain is empty
    fi
    
    echoinfo ""
    # Crypto Mining Prevention Configuration
    echoinfo ""
    echoinfo "${BLUE}Crypto-Mining Prevention Configuration (Optional):${NC}"
    local default_env_patterns="WALLET_ADDRESS=.*,POOL_URL=.*,STRATUM_URL=.*,XMRIG_.*,MINER_.*,MONERO=.*"
    local default_reject_env="false"
    local default_process_names="xmrig,nbminer,t-rex,stratum,minerd,cpuminer,ccminer,ethminer,claymore"

    # shellcheck disable=SC2162
    read -p "Enter suspicious ENV patterns (comma-separated regex, default: \"$default_env_patterns\"): " crypto_env_patterns
    crypto_env_patterns=${crypto_env_patterns:-$default_env_patterns}

    # shellcheck disable=SC2162
    read -p "Reject container creation on suspicious ENV match? (true/false, default: $default_reject_env): " crypto_reject_env
    crypto_reject_env=${crypto_reject_env:-$default_reject_env}
    if [[ "$crypto_reject_env" != "true" && "$crypto_reject_env" != "false" ]]; then
        echoinfo "Invalid input for reject on ENV match. Defaulting to '$default_reject_env'."
        crypto_reject_env="$default_reject_env"
    fi

    # shellcheck disable=SC2162
    read -p "Enter suspicious process names (comma-separated, default: \"$default_process_names\"): " crypto_process_names
    crypto_process_names=${crypto_process_names:-$default_process_names}
    
    echoinfo ""
    echoinfo "Creating/overwriting $env_file with the following settings:"
    echoinfo "API_KEY=*** (hidden for security, will be written to file)"
    echoinfo "JWT_SECRET=*** (hidden for security, will be written to file)"
    echoinfo "PORT=$port"
    if [ -n "$cf_team_domain" ]; then
        echoinfo "CLOUDFLARE_TEAM_DOMAIN=$cf_team_domain"
        echoinfo "CLOUDFLARE_AUDIENCE_TAG=$cf_audience_tag"
    else
        echoinfo "Cloudflare Access integration: DISABLED"
    fi
    echoinfo "CRYPTO_SUSPICIOUS_ENV_PATTERNS=\"$crypto_env_patterns\""
    echoinfo "CRYPTO_REJECT_ON_SUSPICIOUS_ENV=$crypto_reject_env"
    echoinfo "CRYPTO_SUSPICIOUS_PROCESS_NAMES=\"$crypto_process_names\""


    # Create .env file
    {
        echo "API_KEY=$api_key"
        echo "JWT_SECRET=$jwt_secret"
        echo "PORT=$port"
        if [ -n "$cf_team_domain" ]; then
            echo "CLOUDFLARE_TEAM_DOMAIN=$cf_team_domain"
            echo "CLOUDFLARE_AUDIENCE_TAG=$cf_audience_tag"
        fi
        echo ""
        echo "# Crypto-Mining Prevention Settings"
        echo "CRYPTO_SUSPICIOUS_ENV_PATTERNS=\"$crypto_env_patterns\""
        echo "CRYPTO_REJECT_ON_SUSPICIOUS_ENV=$crypto_reject_env"
        echo "CRYPTO_SUSPICIOUS_PROCESS_NAMES=\"$crypto_process_names\""
    } > "$env_file"

    echoinfo ".env file configured successfully."
}

PM2_STARTUP_COMMAND="" # Global variable to store pm2 startup command if needed

setup_service_pm2() {
    local app_dir="$1"
    local service_name="cf-container-service"
    local entry_script="container-service.js"

    echoinfo "Setting up service with pm2..."
    cd "$app_dir" || echoerror "Failed to change directory to $app_dir for pm2 setup."

    if ! check_command pm2; then
        echoinfo "pm2 not found. Installing pm2 globally..."
        if sudo npm install -g pm2; then
            echoinfo "pm2 installed successfully."
        else
            echoerror "Failed to install pm2. Please try installing it manually (sudo npm install -g pm2) and re-run the script or relevant parts."
        fi
    else
        echoinfo "pm2 is already installed."
    fi

    echoinfo "Stopping and deleting any existing '$service_name' pm2 process..."
    pm2 delete "$service_name" || true # Ignore error if process doesn't exist

    echoinfo "Starting '$service_name' with pm2..."
    # Using --env .env --update-env is not standard for pm2 start for .env files.
    # pm2 automatically loads .env from the app's CWD if `node -r dotenv/config your-app.js` is not used.
    # Or, pm2 ecosystem file can specify environment variables.
    # For simplicity, we assume container-service.js loads .env using dotenv.
    if pm2 start "$entry_script" --name "$service_name"; then
        echoinfo "$service_name started successfully via pm2."
    else
        echoerror "Failed to start $service_name via pm2."
    fi

    echoinfo "Attempting to configure pm2 to start on system boot..."
    # The output of `pm2 startup` is a command that needs to be run.
    # We capture it and try to execute it.
    # Storing the output in a variable, then trying to execute it.
    # This can be tricky due to sudo requirements and specific system configurations.
    # The `unbuffer` command might be needed if pm2 startup output is buffered.
    # For simplicity, we'll try to grab the command.
    # If it fails, we'll instruct the user.
    
    # Try to get the systemd command. This is a common case.
    # The exact command can vary based on OS and pm2 version.
    # This part is best-effort.
    PM2_STARTUP_OUTPUT=""
    PM2_STARTUP_OUTPUT=$(pm2 startup systemd -u "$USER" --hp "$HOME" 2>&1) || true 
    
    # Look for a command to execute, typically starting with 'sudo'
    # This regex is a heuristic.
    PM2_EXEC_COMMAND=$(echo "$PM2_STARTUP_OUTPUT" | grep -oP 'sudo\s+.*') || true

    if [ -n "$PM2_EXEC_COMMAND" ]; then
        echoinfo "Attempting to execute the following command for pm2 startup: $PM2_EXEC_COMMAND"
        if $PM2_EXEC_COMMAND; then
            echoinfo "pm2 startup command executed successfully."
            PM2_STARTUP_COMMAND="" # Clear it as it was handled
        else
            echoerror "Failed to execute pm2 startup command automatically."
            echoinfo "Please manually run the command suggested by 'pm2 startup' (usually requires sudo)."
            PM2_STARTUP_COMMAND="$PM2_EXEC_COMMAND" # Store for final instructions
        fi
    else
        # Fallback: just run pm2 startup and let it print instructions
        echoinfo "Could not automatically determine pm2 startup command. Running 'pm2 startup' and saving current process list."
        echoinfo "You might need to manually run a command provided by pm2 to complete startup setup."
        pm2 startup # This will print instructions if needed
        PM2_STARTUP_COMMAND="Run the command output by 'pm2 startup' if any." # Generic instruction
    fi

    echoinfo "Saving current pm2 process list..."
    pm2 save || echoerror "Failed to save pm2 process list."

    echoinfo "Service setup with pm2 completed."
    cd - > /dev/null # Return to previous directory
}

print_final_instructions() {
    local app_dir="$1"
    local env_file="$app_dir/.env"
    local port="<not set>"
    local api_key_display="<not set or hidden>"
    local jwt_secret_display="<not set or hidden>"
    local cf_team_domain_display="Not Configured"
    local cf_audience_tag_display="Not Configured"
    local crypto_reject_env_display="<not set>"
    local crypto_env_patterns_display="<not set>"
    local crypto_process_names_display="<not set>"


    if [ -f "$env_file" ]; then
        # shellcheck disable=SC1090
        . "$env_file" # Source the .env file to get variables
        port="${PORT:-<not set>}" 
        
        api_key_display="${API_KEY:-<not set>}"
        if [ ${#api_key_display} -gt 16 ]; then
            api_key_display="${api_key_display:0:4}...${api_key_display: -4} (obfuscated for display)"
        fi
        
        jwt_secret_display="*** (set in .env, keep secure)"

        if [ -n "${CLOUDFLARE_TEAM_DOMAIN:-}" ] && [ -n "${CLOUDFLARE_AUDIENCE_TAG:-}" ]; then
            cf_team_domain_display="${CLOUDFLARE_TEAM_DOMAIN}"
            cf_audience_tag_display="${CLOUDFLARE_AUDIENCE_TAG}"
        fi
        crypto_reject_env_display="${CRYPTO_REJECT_ON_SUSPICIOUS_ENV:-false}"
        crypto_env_patterns_display="${CRYPTO_SUSPICIOUS_ENV_PATTERNS:-<not set>}"
        crypto_process_names_display="${CRYPTO_SUSPICIOUS_PROCESS_NAMES:-<not set>}"
    fi

    echoinfo "----------------------------------------------------"
    echoinfo "cf-container-service deployment complete!"
    echoinfo "----------------------------------------------------"
    echoinfo "Service is running on port: $port"
    echoinfo "Static API Key (for WebSockets, etc.): $api_key_display"
    echoinfo "JWT Secret for user authentication: $jwt_secret_display"
    if [ "$cf_team_domain_display" != "Not Configured" ]; then
        echoinfo "Cloudflare Team Domain: $cf_team_domain_display"
        echoinfo "Cloudflare Audience Tag: $cf_audience_tag_display"
    else
        echoinfo "Cloudflare Access Integration: Disabled"
    fi
    echoinfo ""
    echoinfo "${BLUE}Crypto-Mining Prevention Settings:${NC}"
    echoinfo "  Reject on suspicious ENV: $crypto_reject_env_display"
    echoinfo "  Suspicious ENV patterns: $crypto_env_patterns_display"
    echoinfo "  Suspicious process names: $crypto_process_names_display"
    echoinfo ""
    echoinfo "Useful pm2 commands:"
    echoinfo "  To check service status: pm2 status cf-container-service"
    echoinfo "  To view logs: pm2 logs cf-container-service"
    echoinfo "  To stop the service: pm2 stop cf-container-service"
    echoinfo "  To restart the service: pm2 restart cf-container-service"
    echoinfo "  To remove from pm2: pm2 delete cf-container-service"
    echoinfo ""
    if [ -n "$PM2_STARTUP_COMMAND" ]; then
        echoinfo "${BLUE}ACTION REQUIRED for PM2 startup on boot:${NC}"
        echoinfo "  If the script failed to run it, or if you saw a specific command from 'pm2 startup' output, please execute it now."
        echoinfo "  The suggested command was: $PM2_STARTUP_COMMAND"
        echoinfo ""
    fi
    echoinfo "${BLUE}Firewall Reminder:${NC}"
    echoinfo "  Remember to configure your firewall to allow traffic on port $port if necessary."
    echoinfo "  Example for ufw: sudo ufw allow $port/tcp"
    echoinfo ""
    if [[ "$OS_FAMILY" == "debian" ]] && grep -q "docker" /etc/group && id -nG "$USER" | grep -qw "docker"; then
         # Check if user was added to docker group during this script run (heuristic)
         # This is a bit complex to check perfectly, so a general reminder is often best.
         # A more reliable way would be to set a flag if usermod was called.
         # For now, this general reminder is fine.
        : # This is a placeholder for a more accurate check if needed
    fi
    echoinfo "${BLUE}Docker Group Reminder:${NC}"
    echoinfo "  If you were added to the 'docker' group during this script, you may need to start a new shell session or re-login for these changes to take full effect."
    echoinfo ""
    echoinfo "Deployment script finished."
}


# --- Initial Execution Flow ---

detect_os # Detect OS first

echoinfo "Starting deployment of cf-container-service..."

# --- Prerequisites Installation ---
echoinfo "Checking and installing prerequisite packages..."
debian_prereqs=("git" "curl" "gnupg" "software-properties-common")
rhel_prereqs=("git" "curl" "gnupg") 

packages_needed=()
if [ "$OS_FAMILY" == "debian" ]; then
    for pkg in "${debian_prereqs[@]}"; do
        if ! check_command "$pkg"; then
            packages_needed+=("$pkg")
        else
            echoinfo "Prerequisite '$pkg' is already installed."
        fi
    done
elif [ "$OS_FAMILY" == "rhel" ]; then
    for pkg in "${rhel_prereqs[@]}"; do
        if ! check_command "$pkg"; then
            packages_needed+=("$pkg")
        else
            echoinfo "Prerequisite '$pkg' is already installed."
        fi
    done
fi

if [ ${#packages_needed[@]} -gt 0 ]; then
    install_packages "${packages_needed[@]}"
else
    echoinfo "All prerequisite packages are already installed."
fi

# --- Node.js Installation ---
NODE_MAJOR_VERSION_TARGET="18" 

echoinfo "Checking for Node.js (target version: ${NODE_MAJOR_VERSION_TARGET}.x)..."
node_version_ok=false
if check_command node; then
    current_node_version=$(node -v)
    echoinfo "Found Node.js version: $current_node_version"
    if [[ "$current_node_version" == "v${NODE_MAJOR_VERSION_TARGET}."* ]]; then
        node_version_ok=true
        echoinfo "Node.js version ${NODE_MAJOR_VERSION_TARGET}.x is already installed and satisfactory."
    else
        echoinfo "Existing Node.js version ($current_node_version) does not match target major version ${NODE_MAJOR_VERSION_TARGET}.x."
    fi
else
    echoinfo "Node.js is not installed."
fi

if [ "$node_version_ok" = false ]; then
    if [ "$OS_FAMILY" == "debian" ]; then
        echoinfo "Installing Node.js ${NODE_MAJOR_VERSION_TARGET}.x for Debian-based system..."
        if ! check_command curl; then echoerror "curl is required but not found."; fi
        SETUP_SCRIPT=$(mktemp)
        curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR_VERSION_TARGET}.x" -o "$SETUP_SCRIPT"
        echoinfo "Running NodeSource setup script..."
        sudo -E bash "$SETUP_SCRIPT"
        rm "$SETUP_SCRIPT"
        install_packages "nodejs"
        if check_command node && check_command npm; then
            echoinfo "Node.js version: $(node -v), npm version: $(npm -v) installed."
        else
            echoerror "Node.js or npm installation failed."
        fi
    elif [ "$OS_FAMILY" == "rhel" ]; then
        echoinfo "Automated Node.js installation for RHEL-based systems is not yet fully implemented."
        echoinfo "Please ensure Node.js (version ${NODE_MAJOR_VERSION_TARGET}.x or compatible) is installed."
    else
        echoerror "Cannot install Node.js: Unsupported OS family '$OS_FAMILY'."
    fi
else
    echoinfo "Node.js check complete. Current version meets requirements."
fi
echoinfo "Initial setup and prerequisite installation phase complete."

# --- Docker Installation ---
install_docker

# --- LXC Installation ---
install_lxc

# --- Application Setup ---
APP_DIR="" 
APP_DIR="$(pwd)" 
setup_app_code "$APP_DIR"

# --- Install Application Dependencies ---
install_app_dependencies "$APP_DIR"
echoinfo "Application setup and dependency installation phase complete."

# --- Configure Application (.env) ---
configure_app "$APP_DIR"

# --- Setup Service with PM2 ---
setup_service_pm2 "$APP_DIR"

# --- Final Instructions ---
print_final_instructions "$APP_DIR"
