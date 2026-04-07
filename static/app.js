document.addEventListener("DOMContentLoaded", () => {
    const hintCards = document.querySelectorAll("[data-tip-toggle]");
    hintCards.forEach((button) => {
        button.addEventListener("click", () => {
            const target = document.getElementById(button.dataset.tipToggle);
            if (!target) {
                return;
            }
            target.hidden = !target.hidden;
            button.setAttribute("aria-expanded", String(!target.hidden));
        });
    });

    const refreshButton = document.getElementById("refresh-app");
    if (refreshButton) {
        refreshButton.addEventListener("click", () => {
            window.location.reload();
        });
    }

    const logoutForm = document.querySelector(".logout-form");
    const sessionTimeoutMs = Number(logoutForm?.dataset.sessionTimeoutMs || 0);
    if (logoutForm && Number.isFinite(sessionTimeoutMs) && sessionTimeoutMs > 0) {
        let timeoutHandle = null;
        let isLoggingOut = false;

        const triggerIdleLogout = () => {
            if (isLoggingOut) {
                return;
            }
            isLoggingOut = true;
            logoutForm.submit();
        };

        const resetIdleTimer = () => {
            if (isLoggingOut) {
                return;
            }
            if (timeoutHandle) {
                window.clearTimeout(timeoutHandle);
            }
            timeoutHandle = window.setTimeout(triggerIdleLogout, sessionTimeoutMs);
        };

        ["click", "keydown", "mousemove", "scroll", "touchstart"].forEach((eventName) => {
            window.addEventListener(eventName, resetIdleTimer, { passive: true });
        });

        resetIdleTimer();
    }
});
