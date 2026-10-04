export const dialogStack = [];
let originalOverflow = '';
const inertElements = new Map();
let observer;
function reconcile() {
  for (const [element, value] of inertElements) element.inert = value;
  inertElements.clear();
  const top = dialogStack.at(-1);
  if (!top?.isConnected) return;
  let branch = top;
  while (branch.parentElement) {
    const parent = branch.parentElement;
    for (const sibling of parent.children) {
      if (sibling === branch || sibling.classList.contains('toast-root') || ['SCRIPT','STYLE','LINK'].includes(sibling.tagName)) continue;
      inertElements.set(sibling, sibling.inert);
      sibling.inert = true;
    }
    if (parent === document.body) break;
    branch = parent;
  }
  top.inert = false;
}
export function enterDialog(element) {
  if (!dialogStack.length) {
    originalOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    observer = new MutationObserver(reconcile);
    observer.observe(document.body, {childList:true,subtree:true});
  }
  dialogStack.push(element);
  reconcile();
  document.dispatchEvent(new Event('wfs:dialogs'));
}
export function leaveDialog(element) {
  const index = dialogStack.indexOf(element);
  if (index >= 0) dialogStack.splice(index,1);
  reconcile();
  if (!dialogStack.length) { observer?.disconnect(); observer = null; document.body.style.overflow = originalOverflow; }
  document.dispatchEvent(new Event('wfs:dialogs'));
}
