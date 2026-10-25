(function() {
  // Prevent context menu
  document.addEventListener("contextmenu", (e) => e.preventDefault());

  // Prevent inspect shortcuts
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "F12" ||
      (e.ctrlKey && e.shiftKey && (e.key === "I" || e.key === "i" || e.key === "J" || e.key === "j" || e.key === "C" || e.key === "c")) ||
      (e.ctrlKey && (e.key === "U" || e.key === "u" || e.key === "S" || e.key === "s"))
    ) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    const card = document.getElementById("portalCard");
    const form = document.getElementById("claimForm");
    const input = document.getElementById("uidInput");
    const btn = document.getElementById("submitBtn");
    const btnLabel = document.getElementById("btnLabel");
    const timer = document.getElementById("cooldownTimer");
    const alertBox = document.getElementById("alertContainer");
    const activeCard = document.getElementById("activeClaimCard");
    const activeUidDisplay = document.getElementById("displayActiveUid");

    let left = parseInt(window.initialCooldownRemaining || "0", 10);
    let loop = null;

    // Expand card on click/touch/focus
    if (card) {
      card.addEventListener("click", () => {
        if (card.classList.contains("is-maintenance")) return;
        card.classList.add("is-active");
      });

      if (input) {
        input.addEventListener("focus", () => {
          if (card.classList.contains("is-maintenance")) return;
          card.classList.add("is-active");
        });

        // Strict physical lock: block any keystroke or paste while locked
        input.addEventListener("keydown", (e) => {
          if (left > 0 || window.maintenanceMode || input.disabled || input.readOnly || window.isDiscordVerified === false) {
            e.preventDefault();
            return false;
          }
        });
        input.addEventListener("paste", (e) => {
          if (left > 0 || window.maintenanceMode || input.disabled || input.readOnly || window.isDiscordVerified === false) {
            e.preventDefault();
            return false;
          }
        });
      }

      const inputContainer = document.getElementById("inputContainer");
      if (inputContainer) {
        inputContainer.addEventListener("click", () => {
          if (window.isDiscordVerified === false) {
            if (window.isDiscordLoggedIn) {
              window.openJoinModal();
            } else {
              const gate = document.querySelector(".discord-gate-card");
              if (gate) {
                gate.scrollIntoView({ behavior: "smooth", block: "center" });
                gate.classList.add("pulse-highlight");
                setTimeout(() => gate.classList.remove("pulse-highlight"), 1200);
              }
              renderAlert("DISCORD REQUIRED", "Please authorize your Discord account above to unlock the UID whitelist.", "warn");
            }
          }
        });
      }

      // Collapse if clicked outside and input is empty
      document.addEventListener("click", (e) => {
        if (!card.contains(e.target)) {
          const val = input ? input.value.trim() : "";
          if (!val && !alertBox.innerHTML.trim()) {
            card.classList.remove("is-active");
            card.classList.remove("has-alert");
          }
        }
      });
    }

    function renderAlert(title, message, level) {
      if (!alertBox) return;
      if (card) {
        card.classList.add("is-active");
        card.classList.add("has-alert");
      }

      const typeClass = (level === "ok" || level === "success") ? "portal-alert-success" : "portal-alert-warn";
      const icon = (level === "ok" || level === "success") ? "✓" : "⚠️";

      alertBox.innerHTML = `
        <div class="portal-alert ${typeClass}">
          <span class="portal-alert-icon">${icon}</span>
          <div class="portal-alert-content">
            <div class="portal-alert-title">${title}</div>
            <div class="portal-alert-message">${message}</div>
          </div>
        </div>
      `;
      alertBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function timeStr(sec) {
      if (sec <= 0) return "READY TO CLAIM";
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = Math.floor(sec % 60);
      const z = (n) => String(n).padStart(2, "0");
      return `${z(h)}h ${z(m)}m ${z(s)}s`;
    }

    function lockInput(claimedUid) {
      if (input) {
        input.disabled = true;
        input.readOnly = true;
        input.classList.add("input-locked");
        if (claimedUid) {
          input.value = claimedUid;
        }
        input.placeholder = "UID Locked (24h Cooldown Active)";
      }
      const inputContainer = document.getElementById("inputContainer");
      if (inputContainer) inputContainer.classList.add("is-locked");
      const lockBadge = document.getElementById("lockBadge");
      if (lockBadge) lockBadge.style.display = "flex";
      const fieldHint = document.getElementById("fieldHint");
      if (fieldHint) fieldHint.textContent = "LOCKED (COOLDOWN ACTIVE)";
      if (btn) {
        btn.disabled = true;
        btn.classList.add("btn-locked");
      }
      if (btnLabel) btnLabel.textContent = "UID Locked";
      const btnIcon = document.getElementById("btnIcon");
      if (btnIcon) btnIcon.textContent = "🔒";
    }

    function unlockInput() {
      if (window.maintenanceMode) return;
      if (window.isDiscordVerified === false) return;
      if (input) {
        input.disabled = false;
        input.readOnly = false;
        input.classList.remove("input-locked");
        input.placeholder = "Enter numeric UID (e.g. 5182947291)";
      }
      const inputContainer = document.getElementById("inputContainer");
      if (inputContainer) inputContainer.classList.remove("is-locked");
      const lockBadge = document.getElementById("lockBadge");
      if (lockBadge) lockBadge.style.display = "none";
      const fieldHint = document.getElementById("fieldHint");
      if (fieldHint) fieldHint.textContent = "NUMBERS ONLY";
      if (btn) {
        btn.disabled = false;
        btn.classList.remove("btn-locked");
      }
      if (btnLabel) btnLabel.textContent = "Add UID";
      const btnIcon = document.getElementById("btnIcon");
      if (btnIcon) btnIcon.textContent = "→";
    }

    function syncTimerDisplay() {
      if (!timer) return;
      if (left > 0) {
        timer.textContent = `${timeStr(left)}`;
        timer.classList.remove("ready");
        timer.classList.add("active");
        const curUid = activeUidDisplay ? activeUidDisplay.textContent.trim() : "";
        lockInput(curUid && curUid !== "—" ? curUid : null);
      } else {
        timer.textContent = "READY TO CLAIM";
        timer.classList.remove("active");
        timer.classList.add("ready");
        unlockInput();
      }
    }

    function runClock() {
      if (loop) clearInterval(loop);
      syncTimerDisplay();
      if (left <= 0) return;
      loop = setInterval(() => {
        left--;
        if (left <= 0) {
          left = 0;
          clearInterval(loop);
          syncTimerDisplay();
          renderAlert("COOLDOWN FINISHED", "24-hour cycle has elapsed. You can now submit an Account UID.", "ok");
        } else {
          syncTimerDisplay();
        }
      }, 1000);
    }

    // Initialize timer
    runClock();

    // Periodic sync with server
    setInterval(async () => {
      try {
        const res = await fetch("/api/status", { cache: "no-store" });
        const val = await res.json();
        if (val && typeof val.cooldown_remaining === "number") {
          if (val.maintenance_mode !== undefined) {
            window.maintenanceMode = Boolean(val.maintenance_mode);
          }
          if (Math.abs(val.cooldown_remaining - left) > 3) {
            left = val.cooldown_remaining;
            runClock();
          }
          if (val.last_claimed_uid && activeCard && activeUidDisplay) {
            activeUidDisplay.textContent = val.last_claimed_uid;
            activeCard.hidden = false;
          }
        }
      } catch (_) {}
    }, 10000);

    // Form submit listener
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();

        // If system is currently under maintenance
        if (window.maintenanceMode) {
          renderAlert(
            "UNDER MAINTENANCE",
            "Free UID whitelist claims are temporarily paused by administration.",
            "warn"
          );
          return;
        }

        // If user already claimed or cooldown active
        if (left > 0) {
          renderAlert(
            "LIMIT REACHED",
            `24 ghante me sirf 1 UID add ho sakta hai. Next claim unlock in: ${timeStr(left)}.`,
            "warn"
          );
          return;
        }

        const raw = (input ? input.value : "").trim();
        if (!/^\d{5,20}$/.test(raw)) {
          renderAlert(
            "INVALID UID",
            "Please enter a valid numeric Account ID (5 to 20 digits).",
            "warn"
          );
          if (input) input.focus();
          return;
        }

        if (btnLabel) btnLabel.textContent = "Processing...";
        btn.disabled = true;

        try {
          const res = await fetch("/api/claim", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ uid: raw })
          });
          const body = await res.json();

          if (res.ok && body.success) {
            renderAlert("SUCCESS", body.message || `UID ${raw} activated for 24 hours.`, "ok");
            left = Number(body.cooldown_remaining || 86400);
            lockInput(raw);
            if (activeCard && activeUidDisplay) {
              activeUidDisplay.textContent = raw;
              activeCard.hidden = false;
            }
            runClock();
          } else {
            renderAlert("WARNING", body.message || "Request could not be processed.", "warn");
            if (body.cooldown_remaining) {
              left = body.cooldown_remaining;
              lockInput();
              runClock();
            }
          }
        } catch (_) {
          renderAlert("NETWORK ERROR", "Unable to connect to server. Please check your connection.", "warn");
        } finally {
          if (left <= 0 && !window.maintenanceMode) {
            btn.disabled = false;
            if (btnLabel) btnLabel.textContent = "Add UID";
          }
        }
      });
    }

    // Active UID copy button
    window.copyActiveUid = function() {
      const v = document.getElementById("displayActiveUid");
      const b = document.getElementById("copyActiveUidBtn");
      if (!v) return;
      const t = v.textContent.trim();
      if (!t || t === "—") return;
      navigator.clipboard.writeText(t).then(() => {
        if (b) {
          const prev = b.textContent;
          b.textContent = "COPIED";
          setTimeout(() => { b.textContent = prev; }, 1400);
        }
      }).catch(() => {});
    };

    // Discord link copy button
    window.copyDiscordLink = function() {
      const b = document.getElementById("copyDiscordBtn");
      const inviteUrl = window.discordInviteDeleteHex || window.discordInviteNova || "https://discord.gg/QDNBcfCAAh";
      navigator.clipboard.writeText(inviteUrl).then(() => {
        if (b) {
          const prev = b.textContent;
          b.textContent = "COPIED";
          setTimeout(() => { b.textContent = prev; }, 1400);
        }
      }).catch(() => {});
    };

    // ==================== DISCORD MODAL & VERIFICATION ====================
    let pollTimer = null;

    window.openJoinModal = function(e) {
      if (e && e.preventDefault) e.preventDefault();
      const modal = document.getElementById("joinServerModal");
      if (modal) {
        modal.classList.remove("is-closing");
        modal.style.display = "flex";
        startGuildPolling();
      }
    };

    window.closeJoinModal = function() {
      const modal = document.getElementById("joinServerModal");
      if (modal) {
        modal.classList.add("is-closing");
        setTimeout(() => {
          modal.style.display = "none";
          modal.classList.remove("is-closing");
        }, 200);
      }
      stopGuildPolling();
    };

    window.handleJoinServerClick = function() {
      const pollStatus = document.getElementById("modalPollStatus");
      const pollText = document.getElementById("pollStatusText");
      if (pollStatus && pollText) {
        pollStatus.className = "modal-poll-status";
        pollText.textContent = "Invite opened! Waiting for you to accept & join...";
      }
      stopGuildPolling();
      pollGuildMembership();
      pollTimer = setInterval(pollGuildMembership, 2000);
    };

    function startGuildPolling() {
      if (pollTimer) return;
      pollTimer = setInterval(pollGuildMembership, 2800);
    }

    function stopGuildPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function applyVerifiedState() {
      window.isDiscordVerified = true;

      const modal = document.getElementById("joinServerModal");
      const pollStatus = document.getElementById("modalPollStatus");
      const pollText = document.getElementById("pollStatusText");
      const verifyBtn = document.getElementById("btnModalVerify");

      if (pollStatus && pollText) {
        pollStatus.className = "modal-poll-status poll-success";
        pollText.textContent = "✓ Verified! You are now a server member.";
      }
      if (verifyBtn) {
        verifyBtn.disabled = true;
        verifyBtn.innerHTML = '<span class="verify-btn-icon">✓</span> Verified';
      }

      setTimeout(() => {
        if (modal) modal.style.display = "none";
      }, 700);

      const chip = document.querySelector(".discord-chip");
      if (chip) {
        chip.classList.remove("chip-unverified");
        chip.classList.add("chip-verified");
        const statusSpan = chip.querySelector(".discord-chip-status");
        if (statusSpan) {
          statusSpan.innerHTML = '<span class="status-dot dot-verified"></span> SERVER MEMBER';
        }
        const chipActions = chip.querySelector(".discord-chip-actions");
        if (chipActions) {
          const joinBtn = chipActions.querySelector(".btn-chip-join");
          const recheckBtn = chipActions.querySelector(".btn-chip-recheck");
          if (joinBtn) joinBtn.remove();
          if (recheckBtn) recheckBtn.remove();
        }
      }

      if (left <= 0 && !window.maintenanceMode) {
        unlockInput();
        if (timer) {
          timer.className = "status-badge ready";
          timer.textContent = "READY TO CLAIM";
        }
      }

      renderAlert("DISCORD VERIFIED", "Welcome to Delete Hex! Your UID whitelist access is unlocked.", "ok");
    }

    async function pollGuildMembership() {
      try {
        const res = await fetch("/auth/discord/check-guild");
        if (!res.ok) return;
        const data = await res.json();
        if (data && data.in_guild) {
          stopGuildPolling();
          applyVerifiedState();
        }
      } catch (_) {}
    }

    window.verifyMemberNow = async function() {
      const verifyBtn = document.getElementById("btnModalVerify");
      const label = document.getElementById("verifyBtnLabel");
      const pollStatus = document.getElementById("modalPollStatus");
      const pollText = document.getElementById("pollStatusText");

      if (verifyBtn) verifyBtn.disabled = true;
      if (label) label.textContent = "Checking membership...";

      try {
        const res = await fetch("/auth/discord/check-guild");
        const data = await res.json();
        if (data && data.in_guild) {
          stopGuildPolling();
          applyVerifiedState();
        } else {
          if (pollStatus && pollText) {
            pollStatus.className = "modal-poll-status poll-warn";
            pollText.textContent = "⚠️ Server not joined yet! Click the Join button above first.";
          }
          renderAlert("NOT IN SERVER", "Please click 'Join Delete Hex Server' to join first, then verify.", "warn");
        }
      } catch (_) {
        if (pollStatus && pollText) {
          pollStatus.className = "modal-poll-status poll-warn";
          pollText.textContent = "Network error while checking. Please try again.";
        }
      } finally {
        if (verifyBtn && !window.isDiscordVerified) {
          verifyBtn.disabled = false;
          if (label) label.textContent = "I Have Joined / Verify Now";
        }
      }
    };

    window.recheckGuildMembership = function() {
      window.openJoinModal();
    };

    // Auto-start polling if modal is rendered on page load
    if (document.getElementById("joinServerModal")) {
      startGuildPolling();
    }
  });
})();
