import { NodeV2 } from "../schema/src/page.ts";
const kid = { id: "k1", type: "Text", props: { content: "hi" } };
const cases: any = {
  "Repeat empty":            { id:"r1", type:"Repeat", props:{path:"",as:"item",keyPath:"id"}, children:[] },
  "Repeat 1 child no source":{ id:"r2", type:"Repeat", props:{path:"",as:"item",keyPath:"id"}, children:[kid] },
  "Repeat 1 child +source":  { id:"r3", type:"Repeat", props:{source:"items",path:"",as:"item",keyPath:"id"}, children:[kid] },
  "Repeat +bind prop":       { id:"r4", type:"Repeat", props:{bind:"items",as:"item",keyPath:"id"}, children:[kid] },
  "Repeat top-level bind":   { id:"r5", type:"Repeat", bind:"items", props:{as:"item",keyPath:"id"}, children:[kid] },
  "Cond empty":              { id:"c1", type:"Conditional", props:{}, children:[] },
  "Cond 1 child no when":    { id:"c2", type:"Conditional", props:{}, children:[kid] },
  "Cond 1 child when=''":    { id:"c3", type:"Conditional", props:{when:""}, children:[kid] },
  "Cond 1 child when=x":     { id:"c4", type:"Conditional", props:{when:"items"}, children:[kid] },
  "DataBoundary empty":      { id:"d1", type:"DataBoundary", props:{fallback:""}, children:[] },
  "DataBoundary 1 child":    { id:"d2", type:"DataBoundary", props:{fallback:""}, children:[kid] },
  "DataBoundary +bind":      { id:"d3", type:"DataBoundary", props:{fallback:"",bind:"items"}, children:[kid] },
  "Slot default":            { id:"s1", type:"Slot", props:{name:"default"} },
  "Slot +style":             { id:"s2", type:"Slot", props:{name:"default"}, style:{width:"420px"} },
  "Slot +children":          { id:"s3", type:"Slot", props:{name:"default"}, children:[kid] },
};
for (const [k, v] of Object.entries(cases)) {
  const r = NodeV2.safeParse(v);
  console.log(k.padEnd(28), r.success ? "PASS" : "FAIL  " + r.error.issues.map((i:any)=>`${i.path.join('.')}: ${i.message}`).join(" | ").slice(0,180));
}
