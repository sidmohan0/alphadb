# Contributing to AlphaDB

Thank you for your interest in contributing! We welcome contributions from everyone.

## 🚀 How to Contribute

### Reporting Issues
- Use GitHub Issues to report bugs or request features
- Include detailed reproduction steps for bugs
- Specify your environment (OS, Docker version, etc.)

### Code Contributions

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```
3. **Make your changes**
   - Follow existing code style
   - Add tests if applicable
   - Update documentation
4. **Test your changes**
   ```bash
   docker compose up -d
   # Test your changes thoroughly
   ```
5. **Commit your changes**
   ```bash
   git commit -m "Add amazing feature"
   ```
6. **Push to your fork**
   ```bash
   git push origin feature/amazing-feature
   ```
7. **Create a Pull Request**

## 📋 Development Guidelines

### Code Style
- **Python**: Follow PEP 8
- **SQL**: Use lowercase with underscores
- **Docker**: Use official base images when possible
- **Documentation**: Clear, concise, with examples

### Commit Messages
- Use conventional commits format
- Examples:
  - `feat: add new exchange integration`
  - `fix: resolve timezone issue in data ingestion`
  - `docs: update setup instructions`

### Testing
- Test all changes locally with Docker Compose
- Verify Grafana dashboards load correctly
- Check data ingestion works as expected

## 🎯 Areas for Contribution

### High Priority
- Additional cryptocurrency exchanges (Binance, Coinbase, etc.)
- More advanced Grafana dashboards (technical indicators)
- Performance optimizations for large datasets
- Unit tests for Python scripts

### Medium Priority
- Additional timeframes (15min, 1hour, 1day aggregates)
- Alert configurations for price movements
- Database backup/restore scripts
- Multi-currency support

### Documentation
- Video tutorials
- Deployment guides for cloud platforms
- API documentation improvements
- Troubleshooting guides

## 🔧 Development Setup

1. **Clone your fork**
   ```bash
   git clone https://github.com/YOUR_USERNAME/alphadb.git
   cd alphadb
   ```

2. **Set up environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Start development stack**
   ```bash
   docker compose up -d
   docker exec -i tsdb psql -U trader -d market < init.sql
   ```

4. **Install Python dependencies**
   ```bash
   pip install ccxt psycopg2-binary
   ```

## 📝 Pull Request Checklist

- [ ] Code follows project style guidelines
- [ ] Changes have been tested locally
- [ ] Documentation updated if needed
- [ ] Commit messages are clear and descriptive
- [ ] No secrets or sensitive data in code
- [ ] Docker services start successfully
- [ ] Grafana dashboards load without errors

## 🤝 Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow
- Maintain a welcoming environment

## 📞 Getting Help

- **Discord**: [Join our community](https://discord.gg/your-discord)
- **GitHub Issues**: For bugs and feature requests
- **Discussions**: For questions and general chat

## 🏆 Recognition

Contributors will be recognized in:
- README.md contributors section
- Release notes for significant contributions
- Project documentation

Thank you for making AlphaDB better for everyone! 🚀