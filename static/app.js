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
});
