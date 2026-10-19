import {chromium} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
const browser=await chromium.launch({headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();
let failed=false;
await page.goto('http://127.0.0.1:8765/?token=development');
await page.getByRole('heading',{name:'Your projects'}).waitFor();
for(const view of ['Projects','Setup & capabilities']){
 if(view!=='Projects')await page.getByRole('button',{name:view}).click();
 await page.waitForTimeout(300);
 const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
 if(results.violations.length)failed=true;
 console.log(view,JSON.stringify(results.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length,examples:v.nodes.slice(0,8).map(n=>({target:n.target,summary:n.failureSummary}))}))));
}
await browser.close();
if(failed)process.exitCode=1;
