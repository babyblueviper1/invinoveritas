# Minimal Dockerfile for invinoveritas MCP Server
FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port (optional, MCP usually uses stdio)
EXPOSE 8080

# Run the MCP server
CMD ["python", "mcp_server.py"]
