# Changelog

## 0.1.0

The first version: stage 0 of the ECB's data plugin, on open-meridian 0.31.0
(contract v26).

- **The ECB's euro foreign exchange reference rates as prices**, one dataset
  (`ecb_fx`): each TARGET business day's rates pushed when the ECB publishes
  them, any past day pulled on a want, each rate the price of the euro's
  cash instrument in the other currency, never inverted.
- **TARGET's calendar read** for the next rates expected and the days the
  ECB publishes nothing on.
- **Raw answers kept from the first day**, in the storage the deployment
  grants.
- **The data role's pages**, Connection (with Sources) and Datasets (with Lag
  and Records), each a read tool on the deployment's MCP.
- **The data suite passes**, stage 0's cases presented.
