// Categories live under /c/ rather than at the root so a category slug can
// never collide with a product slug — both are operator-chosen, and a shop that
// sells a product called "sandals" must not shadow the Sandals category.
//
// The slug is the translated one, so the Arabic category lives at an Arabic
// address, exactly as products do.
export default '/@locale/c/@slug';
