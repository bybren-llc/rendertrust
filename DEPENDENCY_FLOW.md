# 🔄 RenderTrust Dependency Flow & Agent Coordination Guide

> **Visual dependency mapping and coordination guide for AI agents working on RenderTrust**  
> **Date:** May 30, 2025
> **Status:** Active - Reference for all agents

## 🎯 PURPOSE

This document provides a visual dependency flow for all RenderTrust issues across 6 cycles, enabling AI agents to understand:

- 🔗 **Issue Dependencies** - What must be completed before starting work
- 📅 **Cycle Organization** - When issues are scheduled for completion
- ✅ **Readiness Status** - Which issues are ready for agents vs. need decomposition
- 🤝 **Coordination Points** - Where agents need to collaborate

## 📊 CURRENT STATUS

- ✅ **32 Issues Ready for Agents** (Todo status - Green)
- 🔴 **17 Issues Need Decomposition** (Backlog + Labeled - Red)
- 🔗 **Critical Dependencies Mapped** across all 6 cycles
- 🎯 **Perfect for 8-10 Agent Deployment**

### Legend
- 🟢 **Green Issues:** Ready for agents (Todo status)
- 🔴 **Red Issues:** Need decomposition before agent assignment
- ➡️ **Arrows:** Critical dependencies between issues

## 📋 CYCLE BREAKDOWN

### 🔧 Cycle 1: Foundation & Infrastructure (May 26 - Jun 2)
**Total: 9 Issues (4 Ready + 5 Decomposition)**

**✅ Ready for Agents (4 issues):**
- **REN-29:** Database Schema & Migrations
- **REN-32:** Development Environment & Docker Compose
- **REN-33:** End-to-End Encryption (AES-GCM)
- **REN-53:** Gateway FastAPI Framework

**🔴 Needs Decomposition (5 issues):**
- **REN-1:** Coolify Setup (DevOps foundation)
- **REN-2:** Edge Kit Blueprint (major component)
- **REN-13:** Security Architecture (broad scope)
- **REN-18:** Workload Containers (complex)
- **REN-31:** Gateway API Main (parent issue)

### 🚀 Cycle 2: Core Services & Communication (Jun 2 - Jun 16)

**✅ Ready for Agents (8 issues):**
- REN-35: Scheduler Core Framework
- REN-36: Load Balancing Algorithm
- REN-37: Job Dispatch & Tracking
- REN-42: Job Submission API
- REN-49: JSON-RPC Core Implementation
- REN-50: Service Discovery & Routing
- REN-51: A2A Authentication & Authorization
- REN-54: Gateway Auth & Security Middleware

**🔴 Needs Decomposition (5 issues):**
- REN-8: Auto-Scale & Dispatch Flow (parent)
- REN-16: Node Poller (complex monitoring)
- REN-19: Edge Relay Component (major system)
- REN-22: Global Scheduler (parent)
- REN-30: A2A Protocol Implementation (parent)

### 📊 Cycle 3: Processing & Monitoring (Jun 30 - Jul 14)

**✅ Ready for Agents (7 issues):**
- REN-40: Error Handling & Retry Logic
- REN-43: Scheduler-JobRepo Integration
- REN-44: Edge Fleet Health Monitoring
- REN-45: Relay Communication Protocol
- REN-46: Result Processing & Storage
- REN-48: Node Loss Handling
- REN-52: Protocol Documentation & Testing

**🔴 Needs Decomposition (3 issues):**
- REN-10: Monitoring & Observability (broad scope)
- REN-21: Credit Ledger System (complex financial)
- REN-38: Error Handling Parent (parent issue)

### 💰 Cycle 4: Financial & User Experience (Jul 28 - Aug 11)

**✅ Ready for Agents (6 issues):**
- REN-9: Storage Strategy Implementation
- REN-11: Creator UX for GPU-Assist
- REN-41: Coolify API Integration
- REN-47: Credit-Ledger Integration
- REN-55: Gateway API Routes Integration
- REN-56: Gateway OpenAPI & Testing

**🔴 Needs Decomposition (2 issues):**
- REN-3: Community Portal & Leaderboard (full web app)
- REN-20: Billing Service (complex financial)

### 🏢 Cycle 5: Enterprise & Operations (Aug 25 - Sep 8)

**✅ Ready for Agents (6 issues):**
- REN-6: Documentation & Marketing Materials
- REN-24: Logo Asset Creation
- REN-25: DNS Configuration
- REN-26: CI/CD Workflows
- REN-27: Implementation Guide Documentation
- REN-28: Rollup Anchor Blockchain Integration

**🔴 Needs Decomposition (2 issues):**
- REN-4: Disaster Recovery Plan (complex DR strategy)
- REN-7: Vertex AI Integration (AI service integration)

### 🎉 Cycle 6: Release & Polish (Sep 22 - Oct 6)

**✅ Ready for Agents (1 issue):**
- REN-23: v1.0.0-alpha Release Preparation

**Additional Capacity:** Buffer for reruns, final polish, and integration testing

## 🔗 CRITICAL DEPENDENCIES

### ⚠️ Must Complete Before Starting

**Foundation Dependencies:**
- **REN-32 (Dev Environment)** → Required for REN-35 (Scheduler Core)
- **REN-29 (Database)** → Required for REN-35 (Scheduler Core)
- **REN-33 (Encryption)** → Required for REN-51 (A2A Auth)

**Gateway Dependencies:**
- **REN-53 (Gateway Framework)** → Required for REN-54 (Gateway Auth)
- **REN-31 (Gateway Main)** → Parent of REN-53, REN-54, REN-55, REN-56

**Parent-Child Dependencies:**
- **REN-22 (Global Scheduler)** → Parent of REN-35, REN-36, REN-37
- **REN-8 (Auto-Scale Flow)** → Parent of REN-42, REN-43, REN-44, REN-45, REN-46, REN-47, REN-48
- **REN-30 (A2A Protocol)** → Parent of REN-49, REN-50, REN-51, REN-52
- **REN-38 (Error Handling Parent)** → Parent of REN-40

## 🤝 AGENT COORDINATION GUIDELINES

### 🟢 For Todo Issues (Green):
1. **Check Dependencies:** Ensure all prerequisite issues are completed
2. **Claim Issue:** Assign yourself in Linear before starting work
3. **Update Status:** Move from Todo → In Progress → In Review → Done
4. **Coordinate Integration:** Test with dependent components

### 🔴 For Decomposition Issues (Red):
1. **Do NOT start implementation** - these need breakdown first
2. **Planning agents only:** Use /specs templates for decomposition
3. **Create sub-issues:** Break into 2-5 day agent-ready tasks
4. **Update parent:** Link sub-issues and mark parent as tracker

### ⚠️ Coordination Points:
- **Database Schema (REN-29):** Coordinate with all data-dependent issues
- **Gateway Framework (REN-53):** Foundation for all gateway features
- **A2A Protocol (REN-49-52):** Critical for inter-service communication
- **Error Handling (REN-40):** Integrate with all service components

## 📞 QUICK REFERENCE

- **Linear Board:** https://linear.app/wordstofilmby/team/REN/all
- **Repository:** https://github.com/cheddarfox/rendertrust
- **Specs Templates:** /specs folder in repository
- **Confluence Guide:** [Dependency Flow Guide](https://cheddarfox.atlassian.net/wiki/spaces/WA/pages/278396930)
- **Gap Analysis:** [Critical Gap Analysis](https://cheddarfox.atlassian.net/wiki/spaces/WA/pages/277970947)

## 📈 VELOCITY TRACKING

**Target Capacity:** 8-10 agents per 2-week cycle
**Success Rate Target:** 90% completion with 10% rerun buffer

**Cycle Velocity Goals:**
- **Cycle 1:** 4 ready issues (foundation validation)
- **Cycle 2:** 8 ready issues (peak agent utilization)
- **Cycle 3:** 7 ready issues (processing & monitoring)
- **Cycle 4:** 6 ready issues (financial & UX)
- **Cycle 5:** 6 ready issues (enterprise features)
- **Cycle 6:** 1+ issues (release & polish)

## 🚨 IMPORTANT NOTES

1. **Always check Linear** for current issue status before starting work
2. **Dependencies are critical** - don't start work on blocked issues
3. **Coordinate with other agents** when working on integration points
4. **Use proper workflow** - Todo → In Progress → In Review → Done
5. **Document everything** - update specs, README files, and comments

---

*This dependency flow is updated in real-time as issues progress. Always check Linear for current status before starting work.*

**Last Updated:** May 30, 2025
**Next Review:** Weekly during cycle planning

**Contact:** Scott Graham (scott@wordstofilmby.com)  
**Sponsored by:** [WordsToFilmBy.com](https://www.wordstofilmby.com)
