Attribute VB_Name = "FastPlot"
Private Sub Test()
''    Set ws = ThisWorkbook.Sheets("FastPlot")
''    Set TextBox = ws.TextBox1
''    Debug.Print TextBox.Text
'
'    Dim ws As Worksheet
'    Set ws = ActiveSheet
'
'    ' 示例数据数组
'    Dim data(1 To 10, 1 To 2) As Variant
'    Dim i As Long
'
'    ' 填充数据数组
'    For i = 1 To 10
'        data(i, 1) = i ' X 轴数据
'        data(i, 2) = i * 2 ' Y 轴数据
'    Next i
'
'    ' 创建一个新的图表对象
'    Dim chartObj As ChartObject
'    Set chartObj = ws.ChartObjects.Add(Left:=1000, Width:=400, Top:=50, Height:=300)
'
'    ' 获取图表对象
'    Dim chart As chart
'    Set chart = chartObj.chart
'
'    ' 设置图表类型为折线图
'    chart.ChartType = xlXYScatterSmooth
'
'    ' 添加数据系列
'    With chart.SeriesCollection.NewSeries
'        .XValues = Application.Index(data, , 1) ' X 轴数据
'        .Values = Application.Index(data, , 2) ' Y 轴数据
'        .Name = "Sample Data"
'    End With
'
'    ' 设置图表标题
'    chart.HasTitle = True
'    chart.ChartTitle.Text = "Sample Line Chart"
'
'    ' 设置轴标题
'    chart.Axes(xlCategory, xlPrimary).HasTitle = True
'    chart.Axes(xlCategory, xlPrimary).AxisTitle.Text = "X Axis"
'
'    chart.Axes(xlValue, xlPrimary).HasTitle = True
'    chart.Axes(xlValue, xlPrimary).AxisTitle.Text = "Y Axis"
'
'    'MsgBox "Chart created successfully.", vbInformation
    UserForm1.Show

    'MsgBox "hello world"

End Sub

